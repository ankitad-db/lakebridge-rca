"""Generate a realistic demo RCA bundle so the App renders with zero workspace setup.

Mirrors the bundled pilot (Snowflake -> Databricks retail migration): a mix of
migration-induced defects, a genuine data difference, a benign representation diff,
and clean tables. Writes app/bundles/rca_demo/ via the real engine report writer.

Run:  python app/scripts/make_sample_bundle.py
"""

from __future__ import annotations

import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_APP)
sys.path.insert(0, _ROOT)  # import the source engine

from rca_engine.models import (  # noqa: E402
    Evidence,
    Finding,
    Hypothesis,
    MismatchSample,
    RcaResult,
    ReconType,
    RootCauseCategory,
    TableSummary,
    Verdict,
)
from rca_engine.report import write_rca_bundle  # noqa: E402

CAT = "fevm_ps_dr_us_east_2_catalog"


def _f(target, column, recon_type, mism, total, *, category, verdict, conf,
       rationale, remediation, owner, samples=None, confirmed=False, query=None):
    ev = [Evidence(label="probe", detail=rationale)]
    if query:
        ev.append(Evidence(label="confirm", detail="Executed confirmation query.",
                           query=query, data={"confirmed": confirmed}))
    f = Finding(
        recon_id="demo", source_table=f"{CAT}.mig_source_sim.{target}",
        target_table=f"{CAT}.mig_target.{target}", recon_type=recon_type,
        column=column, mismatch_count=mism, total_count=total,
        samples=[MismatchSample(keys=s[0], column=column, source_value=s[1], target_value=s[2])
                 for s in (samples or [])],
    )
    f.hypotheses = [Hypothesis(category=category, verdict=verdict, confidence=conf,
                               rationale=rationale, remediation=remediation, recommended_owner=owner,
                               evidence=ev)]
    return f


def build() -> RcaResult:
    findings = [
        _f("fact_order_items", "amount", ReconType.COLUMN_MISMATCH, 1180, 1500,
           category=RootCauseCategory.TYPE_PRECISION, verdict=Verdict.MIGRATION_INDUCED, conf=0.96,
           rationale="Target AMOUNT is DECIMAL(18,2) vs source DECIMAL(18,4); scale-4 digits are lost.",
           remediation="Migrate AMOUNT as DECIMAL(18,4) to preserve source scale.",
           owner="migration engineer",
           samples=[({"order_item_id": 11}, "12.3457", "12.35"), ({"order_item_id": 21}, "8.6789", "8.68")],
           confirmed=True, query="SELECT s.amount, t.amount FROM src s JOIN tgt t USING(order_item_id) WHERE s.amount<>t.amount"),
        _f("fact_orders", "order_ts", ReconType.COLUMN_MISMATCH, 480, 480,
           category=RootCauseCategory.TIMEZONE, verdict=Verdict.MIGRATION_INDUCED, conf=0.93,
           rationale="Constant +5:30 offset on every row; TIMESTAMP_LTZ not normalized to UTC on load.",
           remediation="Normalize ORDER_TS to UTC (convert_timezone) during the load.",
           owner="migration engineer",
           samples=[({"order_id": 1}, "2026-07-01 10:00:00", "2026-07-01 15:30:00")],
           confirmed=True, query="SELECT DISTINCT unix_timestamp(t.order_ts)-unix_timestamp(s.order_ts) FROM ..."),
        _f("fact_orders", None, ReconType.MISSING_IN_TARGET, 20, 500,
           category=RootCauseCategory.VOLUME_MISSING, verdict=Verdict.MIGRATION_INDUCED, conf=0.9,
           rationale="20 source rows (order_id>480) never landed; a load watermark drops late rows.",
           remediation="Remove/adjust the WHERE order_id<=480 watermark in the load.",
           owner="migration engineer", confirmed=True,
           query="SELECT count(*) FROM src WHERE order_id>480"),
        _f("agg_daily_sales", "revenue", ReconType.COLUMN_MISMATCH, 42, 150,
           category=RootCauseCategory.TRANSPILATION, verdict=Verdict.MIGRATION_INDUCED, conf=0.88,
           rationale="REVENUE rounded to whole units vs source exact SUM; ROUND rounding-mode diff.",
           remediation="Match the source aggregation (no ROUND, or half-up to scale 2).",
           owner="migration engineer",
           samples=[({"store_id": 1, "sales_date": "2026-07-01"}, "1234.56", "1235")]),
        _f("dim_product", "sku", ReconType.COLUMN_MISMATCH, 30, 30,
           category=RootCauseCategory.STRING_FORMAT, verdict=Verdict.MIGRATION_INDUCED, conf=0.85,
           rationale="SKU lower-cased with trailing whitespace during the transform.",
           remediation="Preserve source casing; trim trailing spaces.",
           owner="migration engineer",
           samples=[({"product_id": 1}, "SKU-0001", "sku-0001  ")]),
        _f("dim_customer", "loyalty_tier", ReconType.COLUMN_MISMATCH, 100, 100,
           category=RootCauseCategory.UPSTREAM_DRIFT, verdict=Verdict.GENUINE_DATA, conf=0.82,
           rationale="Source LOYALTY_TIER is NULL for all rows while target is populated — a genuine "
                     "data/provenance difference, not a migration bug.",
           remediation="Route to the data owner: confirm whether target enrichment is intended.",
           owner="data owner", confirmed=True,
           query="SELECT count(*) FROM src WHERE loyalty_tier IS NULL"),
        _f("dim_customer", "attributes", ReconType.COLUMN_MISMATCH, 100, 100,
           category=RootCauseCategory.SEMI_STRUCTURED, verdict=Verdict.BENIGN, conf=0.9,
           rationale="VARIANT re-serialized with keys reordered; payloads are semantically equal.",
           remediation="No action (representation-only).", owner="—",
           samples=[({"customer_id": 1}, '{"segment":"A","channel":"web"}', '{"channel":"web","segment":"A"}')]),
        _f("fact_payments", None, ReconType.MISSING_IN_SOURCE, 10, 60,
           category=RootCauseCategory.VOLUME_EXTRA, verdict=Verdict.NEEDS_REVIEW, conf=0.6,
           rationale="10 extra target rows; likely a non-idempotent re-load fan-out. Confirm dedup.",
           remediation="Make the merge idempotent; dedupe on the natural key.",
           owner="migration engineer"),
    ]

    summaries = [
        TableSummary(f"{CAT}.mig_source_sim.fact_order_items", f"{CAT}.mig_target.fact_order_items",
                     source_count=1500, target_count=1510, absolute_mismatch=1180,
                     mismatch_columns=["amount"], join_keys=["order_item_id"]),
        TableSummary(f"{CAT}.mig_source_sim.fact_orders", f"{CAT}.mig_target.fact_orders",
                     source_count=500, target_count=480, missing_in_target=20, absolute_mismatch=480,
                     mismatch_columns=["order_ts"], join_keys=["order_id"], date_column="order_ts"),
        TableSummary(f"{CAT}.mig_source_sim.agg_daily_sales", f"{CAT}.mig_target.agg_daily_sales",
                     source_count=150, target_count=150, absolute_mismatch=42,
                     mismatch_columns=["revenue"], join_keys=["store_id", "sales_date"], date_column="sales_date"),
        TableSummary(f"{CAT}.mig_source_sim.dim_product", f"{CAT}.mig_target.dim_product",
                     source_count=30, target_count=30, absolute_mismatch=30,
                     mismatch_columns=["sku"], join_keys=["product_id"]),
        TableSummary(f"{CAT}.mig_source_sim.dim_customer", f"{CAT}.mig_target.dim_customer",
                     source_count=100, target_count=100, absolute_mismatch=100,
                     mismatch_columns=["loyalty_tier", "attributes"], join_keys=["customer_id"]),
        TableSummary(f"{CAT}.mig_source_sim.fact_payments", f"{CAT}.mig_target.fact_payments",
                     source_count=50, target_count=60, missing_in_source=10, join_keys=["payment_id"]),
        TableSummary(f"{CAT}.mig_source_sim.dim_store", f"{CAT}.mig_target.dim_store",
                     source_count=5, target_count=5, join_keys=["store_id"]),
    ]
    return RcaResult(recon_id="demo", dialect="snowflake", findings=findings, table_summaries=summaries)


def main():
    out = os.path.join(_APP, "bundles")
    folder = write_rca_bundle(build(), out, "demo", combined=False)
    print(f"Wrote demo bundle -> {folder}")


if __name__ == "__main__":
    main()
