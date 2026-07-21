"""Generate realistic demo RCA bundles so the App is testable without a workspace.

Produces several recon runs — each with a Lakebridge-style UUID ``recon_id`` — driven
by the ground-truth oracle in ``migration/scenarios.yaml``:

  * Retail pilot cutover   (S-series: precision, timezone, volume, string, genuine, ...)
  * Edge-case hardening    (E-series: float repr, int overflow, sentinels, env config, ...)
  * Clean re-run           (post-fix: every table reconciles 100% -> the ✅ path)

Category / verdict / mechanism come from the oracle (single source of truth); this script
only overlays realistic volumetrics (row counts, mismatch counts) and writes each bundle via
the real engine report writer, plus a ``meta.json`` (title/started/source) for the runs list.

Run:  python app/scripts/make_sample_bundle.py
"""

from __future__ import annotations

import json
import os
import sys

import yaml

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

CONFIDENCE = {
    "migration_induced": 0.92,
    "genuine_data": 0.82,
    "benign": 0.9,
    "needs_review": 0.58,
}

# Remediation + owner keyed by (category, verdict); mechanism/rationale come from the oracle.
PLAYBOOK: dict[tuple[str, str], tuple[str, str]] = {
    ("type_precision", "migration_induced"): (
        "Match the source numeric type/scale — keep DECIMAL(p,s); avoid casting to DOUBLE/INT.",
        "migration engineer"),
    ("timezone", "migration_induced"): (
        "Normalize timestamps to UTC on load (convert_timezone) so the constant offset disappears.",
        "migration engineer"),
    ("timezone", "needs_review"): (
        "Offset varies per row — inspect source timezone handling before applying a single fix.",
        "migration engineer"),
    ("semi_structured", "benign"): (
        "No action — JSON keys reordered; payloads are semantically equal.",
        "—"),
    ("semi_structured", "needs_review"): (
        "Values genuinely differ (not a reorder) — confirm the intended value with the data owner.",
        "data owner"),
    ("string_format", "migration_induced"): (
        "Preserve source casing and trim/normalize (whitespace, Unicode NFC) on load.",
        "migration engineer"),
    ("transpilation", "migration_induced"): (
        "Match the source aggregation/rounding semantics (avoid ROUND rounding-mode drift).",
        "migration engineer"),
    ("volume_missing", "migration_induced"): (
        "Remove/adjust the load filter (watermark) that drops late source rows.",
        "migration engineer"),
    ("volume_extra", "migration_induced"): (
        "Make the merge idempotent; dedupe on the natural key to remove fan-out duplicates.",
        "migration engineer"),
    ("upstream_drift", "genuine_data"): (
        "Route to the data owner — a real source/upstream difference, not a migration bug.",
        "data owner"),
    ("upstream_drift", "needs_review"): (
        "Human decision required: confirm whether the target-only values are intended.",
        "data owner"),
    ("null_boolean", "migration_induced"): (
        "Align null/boolean encoding with source (Y/N, 1/0, NULL vs ''/sentinel).",
        "migration engineer"),
    ("env_config", "migration_induced"): (
        "Align session config (e.g., week-start day) between the source and Spark.",
        "migration engineer"),
}


def _playbook(category: str, verdict: str, recon_type: str) -> tuple[str, str]:
    if recon_type == "schema":
        return ("Reconcile the schema change: column rename + type widening + nullability.",
                "migration engineer")
    return PLAYBOOK.get((category, verdict), ("Investigate further.", "migration engineer"))


def _load_oracle() -> dict[str, dict]:
    path = os.path.join(_ROOT, "migration", "scenarios.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    return {s["id"]: s for s in data["scenarios"]}


ORACLE = _load_oracle()


def _finding(recon_id, src_schema, tgt_schema, table, scen_id, *,
             mismatch, total, missing_t=0, missing_s=0, confirmed=False, query=None):
    scen = ORACLE[scen_id]
    category = scen["category"]
    verdict = scen["verdict"]
    recon_type = scen["recon_type"]
    remediation, owner = _playbook(category, verdict, recon_type)

    ev = [Evidence(label="probe", detail=scen["mechanism"])]
    if query:
        ev.append(Evidence(label="confirm", detail="Executed confirmation query.",
                           query=query, data={"confirmed": confirmed}))

    samples = []
    ex = scen.get("example")
    if ex and recon_type == "column_mismatch":
        key_col = f"{table.split('_')[-1]}_id"
        samples = [MismatchSample(keys={key_col: 1}, column=scen.get("column"),
                                  source_value=ex.get("source"), target_value=ex.get("target"))]

    f = Finding(
        recon_id=recon_id,
        source_table=f"{CAT}.{src_schema}.{table}",
        target_table=f"{CAT}.{tgt_schema}.{table}",
        recon_type=ReconType(recon_type),
        column=scen.get("column"),
        mismatch_count=mismatch, total_count=total, samples=samples,
    )
    f.hypotheses = [Hypothesis(
        category=RootCauseCategory(category), verdict=Verdict(verdict),
        confidence=CONFIDENCE[verdict], rationale=scen["mechanism"],
        remediation=remediation, recommended_owner=owner, evidence=ev,
    )]
    return f, missing_t, missing_s


def _table(recon_id, src_schema, tgt_schema, table, *, src, tgt,
           col_scens: dict[str, int] | None = None, row_scens: list[dict] | None = None,
           abs_mismatch=0, schema_ok=True, join_keys=None, date_col=None):
    """Build the findings + TableSummary for one reconciled table pair."""
    findings = []
    missing_t = missing_s = 0
    for scen_id, mism in (col_scens or {}).items():
        f, mt, ms = _finding(recon_id, src_schema, tgt_schema, table, scen_id,
                             mismatch=mism, total=src)
        findings.append(f)
    for row in (row_scens or []):
        f, mt, ms = _finding(recon_id, src_schema, tgt_schema, table, row["scen"],
                             mismatch=row["count"], total=src,
                             missing_t=row.get("missing_t", 0), missing_s=row.get("missing_s", 0),
                             confirmed=row.get("confirmed", False), query=row.get("query"))
        findings.append(f)
        missing_t += row.get("missing_t", 0)
        missing_s += row.get("missing_s", 0)

    mismatch_cols = [ORACLE[s].get("column") for s in (col_scens or {}) if ORACLE[s].get("column")]
    summary = TableSummary(
        source_table=f"{CAT}.{src_schema}.{table}",
        target_table=f"{CAT}.{tgt_schema}.{table}",
        source_count=src, target_count=tgt,
        missing_in_target=missing_t, missing_in_source=missing_s,
        absolute_mismatch=abs_mismatch, mismatch_columns=mismatch_cols,
        schema_ok=schema_ok, join_keys=join_keys or [], date_column=date_col,
    )
    return findings, summary


# --------------------------------------------------------------------------- #
# Run 1 — Retail pilot cutover (S-series + clean dim_store)
# --------------------------------------------------------------------------- #
def build_pilot(recon_id: str) -> RcaResult:
    src, tgt = "mig_source_sim", "mig_target"
    findings: list[Finding] = []
    summaries: list[TableSummary] = []

    fs, s = _table(recon_id, src, tgt, "fact_order_items", src=2000, tgt=2015,
                   col_scens={"S1": 1200},
                   row_scens=[{"scen": "S7", "count": 15, "missing_s": 15,
                               "confirmed": True,
                               "query": "SELECT count(*) FROM tgt GROUP BY order_item_id HAVING count(*)>1"}],
                   abs_mismatch=1200, join_keys=["order_item_id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "fact_orders", src=500, tgt=480,
                   col_scens={"S2": 480},
                   row_scens=[{"scen": "S6", "count": 20, "missing_t": 20, "confirmed": True,
                               "query": "SELECT count(*) FROM src WHERE order_id > 480"}],
                   abs_mismatch=480, join_keys=["order_id"], date_col="order_ts")
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "dim_customer", src=1000, tgt=1000,
                   col_scens={"S3": 1000, "S8": 40, "S9a": 1000, "S9b": 30, "S10": 1000},
                   abs_mismatch=1000, join_keys=["customer_id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "dim_product", src=200, tgt=200,
                   col_scens={"S4": 200}, abs_mismatch=200, join_keys=["product_id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "agg_daily_sales", src=365, tgt=365,
                   col_scens={"S5": 120}, abs_mismatch=120,
                   join_keys=["store_id", "sales_date"], date_col="sales_date")
    findings += fs
    summaries.append(s)

    # C1 — clean 1:1 copy.
    _, s = _table(recon_id, src, tgt, "dim_store", src=50, tgt=50, join_keys=["store_id"])
    summaries.append(s)

    return RcaResult(recon_id=recon_id, dialect="snowflake", findings=findings, table_summaries=summaries)


# --------------------------------------------------------------------------- #
# Run 2 — Edge-case hardening (E-series)
# --------------------------------------------------------------------------- #
def build_edge(recon_id: str) -> RcaResult:
    src, tgt = "mig_edge_source", "mig_edge_target"
    findings: list[Finding] = []
    summaries: list[TableSummary] = []

    fs, s = _table(recon_id, src, tgt, "edge_numeric", src=5000, tgt=5000,
                   col_scens={"E1": 5000, "E2": 3}, abs_mismatch=5000, join_keys=["id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "edge_events", src=10000, tgt=10000,
                   col_scens={"E3": 2500}, abs_mismatch=2500, join_keys=["event_id"],
                   date_col="event_ts")
    findings += fs
    summaries.append(s)

    # E4 — schema-level change.
    fs, s = _table(recon_id, src, tgt, "edge_geo", src=800, tgt=800,
                   row_scens=[{"scen": "E4", "count": 1}], abs_mismatch=0, schema_ok=False,
                   join_keys=["geo_id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "agg_weekly_sales", src=104, tgt=104,
                   col_scens={"E5": 104}, abs_mismatch=104,
                   join_keys=["store_id", "week_start"], date_col="week_start")
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "dim_supplier", src=300, tgt=300,
                   col_scens={"E6": 5}, abs_mismatch=5, join_keys=["supplier_id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "dim_config", src=20, tgt=20,
                   col_scens={"E7": 3}, abs_mismatch=3, join_keys=["config_id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "fact_inventory", src=4000, tgt=4000,
                   col_scens={"E8": 60}, abs_mismatch=60, join_keys=["sku_id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "dim_flag", src=100, tgt=100,
                   col_scens={"E9": 100}, abs_mismatch=100, join_keys=["id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "fact_payments", src=5990, tgt=6000,
                   row_scens=[{"scen": "E10", "count": 10, "missing_s": 10, "confirmed": True,
                               "query": "SELECT count(*) FROM tgt GROUP BY payment_id HAVING count(*)>1"}],
                   abs_mismatch=0, join_keys=["payment_id"])
    findings += fs
    summaries.append(s)

    fs, s = _table(recon_id, src, tgt, "edge_string", src=1500, tgt=1500,
                   col_scens={"E11": 1500, "E12": 200}, abs_mismatch=1500, join_keys=["id"])
    findings += fs
    summaries.append(s)

    return RcaResult(recon_id=recon_id, dialect="snowflake", findings=findings, table_summaries=summaries)


# --------------------------------------------------------------------------- #
# Run 3 — Clean re-run (post-fix): every table reconciles 100%
# --------------------------------------------------------------------------- #
def build_clean(recon_id: str) -> RcaResult:
    src, tgt = "mig_source_sim", "mig_target"
    tables = {"fact_order_items": 2000, "fact_orders": 500, "dim_customer": 1000,
              "dim_product": 200, "agg_daily_sales": 365, "dim_store": 50}
    summaries = [TableSummary(
        source_table=f"{CAT}.{src}.{t}", target_table=f"{CAT}.{tgt}.{t}",
        source_count=n, target_count=n, join_keys=["id"]) for t, n in tables.items()]
    return RcaResult(recon_id=recon_id, dialect="snowflake", findings=[], table_summaries=summaries)


# Stable, Lakebridge-style recon_ids (UUIDv4 shape) so committed bundles are reproducible.
RUNS = [
    {"recon_id": "a3f9c1e2-7b64-4d0a-9c31-6f2b8e5d41aa",
     "title": "Retail pilot cutover — Snowflake → Databricks",
     "started": "2026-07-20T09:14:03Z", "source": "Snowflake (PROD_RETAIL)",
     "builder": build_pilot},
    {"recon_id": "b7e2d4c8-1a35-4f9e-8d20-3c6a9b1e77bf",
     "title": "Edge-case hardening run",
     "started": "2026-07-20T14:41:20Z", "source": "Snowflake (PROD_EDGE)",
     "builder": build_edge},
    {"recon_id": "c1d8f0a6-9e47-42b3-a5c9-8b4d2e6f0139",
     "title": "Clean re-run (post-fix validation)",
     "started": "2026-07-21T08:02:55Z", "source": "Snowflake (PROD_RETAIL)",
     "builder": build_clean},
]


def main():
    out = os.path.join(_APP, "bundles")
    for run in RUNS:
        result = run["builder"](run["recon_id"])
        folder = write_rca_bundle(result, out, run["recon_id"], combined=False)
        meta = {"recon_id": run["recon_id"], "title": run["title"],
                "started": run["started"], "source": run["source"], "dialect": result.dialect}
        with open(os.path.join(folder, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
        print(f"[{run['title']}]  recon_id={run['recon_id']}  "
              f"tables={len(result.table_summaries)} findings={len(result.findings)}")
        print(f"   -> {folder}")


if __name__ == "__main__":
    main()
