"""Tests for the AVF validation source — the second (Lakebridge-agnostic) ingest path.

A routing fake runner returns canned ``avf_*`` rows by table name so the AVF adapter can be
exercised offline. These assert the normalized model matches what the Lakebridge reader
produces (so classify/drilldown/report work unchanged), dialect auto-detection, and that
AVF's own row-count RCA lands as evidence (never as our verdict)."""

from __future__ import annotations

from rca_engine.analyze import analyze
from rca_engine.ingest_avf import attach_avf_rca_evidence, ingest_avf
from rca_engine.models import Hypothesis, ReconType, RootCauseCategory, Verdict
from rca_engine.sources import AVFSource, LakebridgeSource

RS = "cat.validation_reports"

_SUMMARY = [{
    "source_catalog": "edw", "source_schema": "sales", "source_entity": "fact_sales",
    "target_catalog": "lake", "target_schema": "sales", "target_entity": "fact_sales",
    "source_dialect": "teradata",
    "source_total_rows": 1000, "target_total_rows": 995,
    "source_only_rows": 5, "target_only_rows": 0, "mismatched_rows": 12,
    "primary_keys_used": "order_id", "schema_validation_status": "FAIL",
    "overall_status": "FAIL",
}]
_COLS = [
    {"target_entity": "fact_sales", "target_catalog": "lake", "target_schema": "sales",
     "source_catalog": "edw", "source_schema": "sales", "source_entity": "fact_sales",
     "source_column_name": "amount", "target_column_name": "amount",
     "source_column_value": "10.00", "target_column_value": "10.0",
     "row_identifier": '{"order_id": 1}', "mismatch_type": "VALUE",
     "column_datatype": "decimal", "total_rows_with_column_mismatches": 12},
    {"target_entity": "fact_sales", "target_catalog": "lake", "target_schema": "sales",
     "source_catalog": "edw", "source_schema": "sales", "source_entity": "fact_sales",
     "source_column_name": "amount", "target_column_name": "amount",
     "source_column_value": "20.00", "target_column_value": "20.0",
     "row_identifier": '{"order_id": 2}', "mismatch_type": "VALUE",
     "column_datatype": "decimal", "total_rows_with_column_mismatches": 12},
]
_ROWS = [
    {"target_entity": "fact_sales", "target_catalog": "lake", "target_schema": "sales",
     "row_identifier": '{"order_id": 99}', "missing_in_target": True,
     "missing_in_source": False, "mismatched_columns": ""},
]
_SCHEMA = [
    {"target_entity": "fact_sales", "source_column_name": "amount", "target_column_name": "amount",
     "source_data_type": "NUMBER", "target_data_type": "DECIMAL",
     "source_length": 18, "target_length": 18, "source_scale": 4, "target_scale": 2,
     "source_nullable": True, "target_nullable": True,
     "mismatch_type": "TYPE_DIFF", "severity": "WARNING"},
]
_RCA = [
    {"failed_table": "lake.sales.fact_sales", "cause_classification": "FILTER_LOSS",
     "confidence": 0.9, "primary_suspect": "edw.sales.stg_sales", "primary_suspect_edge": "stg → fact",
     "row_deficit": 5, "recommendations": ["Check the WHERE clause on stg_sales"],
     "upstream_notebooks": ["/nb/build_fact"], "problematic_notebooks": ["/nb/build_fact"],
     "problematic_jobs": ["job_42"]},
]


class RoutingRunner:
    """Returns canned rows based on which avf_* table the SQL names."""

    def __init__(self, **tables):
        self.tables = tables
        self.calls: list[str] = []

    def query(self, sql: str):
        self.calls.append(sql)
        for name, rows in self.tables.items():
            if name in sql:
                return rows
        return []


_BI = [
    {"query_name": "daily_revenue", "status": "FAIL",
     "source_total": 1000000.0, "target_total": 999000.0,
     "variance_pct": 0.1, "variance_absolute": 1000, "tolerance_threshold": 0.0,
     "comparison_type": "AGGREGATE", "grain_columns": "store_id", "metric_columns": "revenue",
     "source_system": "TERADATA", "report_name": "revenue_by_store"},
    {"query_name": "row_counts", "status": "PASS",   # within tolerance -> ignored
     "source_total": 500.0, "target_total": 500.0, "variance_pct": 0.0, "variance_absolute": 0,
     "tolerance_threshold": 0.0, "comparison_type": "AGGREGATE", "grain_columns": "",
     "metric_columns": "cnt", "source_system": "TERADATA", "report_name": "row_counts"},
]


def _runner(**overrides):
    tables = {
        "avf_validation_summary": _SUMMARY,
        "avf_validation_columns_mismatch": _COLS,
        "avf_validation_rows_mismatch": _ROWS,
        "avf_validation_schema_mismatch": _SCHEMA,
        "avf_validation_rca": _RCA,
        "avf_validation_bi_results": _BI,
    }
    tables.update(overrides)
    return RoutingRunner(**tables)


def test_ingest_avf_normalizes_all_types():
    findings, summaries, dialect = ingest_avf(_runner(), "run1", RS)
    assert dialect == "teradata"
    kinds = {f.recon_type for f in findings}
    assert ReconType.COLUMN_MISMATCH in kinds
    assert ReconType.MISSING_IN_TARGET in kinds
    assert ReconType.SCHEMA in kinds

    col = next(f for f in findings if f.recon_type == ReconType.COLUMN_MISMATCH)
    assert col.column == "amount"
    assert col.target_table == "lake.sales.fact_sales"
    assert col.mismatch_count == 12          # from total_rows_with_column_mismatches
    assert len(col.samples) == 2
    assert col.samples[0].keys == {"order_id": 1}
    assert col.samples[0].source_value == "10.00"

    vol = next(f for f in findings if f.recon_type == ReconType.MISSING_IN_TARGET)
    assert vol.mismatch_count == 5
    assert vol.samples[0].keys == {"order_id": 99}
    assert vol.metadata.get("avf_rca", {}).get("cause_classification") == "FILTER_LOSS"

    sch = next(f for f in findings if f.recon_type == ReconType.SCHEMA)
    diff = sch.metadata["schema_diffs"][0]
    assert diff["source_datatype"] == "NUMBER(18,4)"
    assert diff["databricks_datatype"] == "DECIMAL(18,2)"

    s = next(x for x in summaries if x.target_table == "lake.sales.fact_sales")
    assert s.source_count == 1000 and s.target_count == 995
    assert s.missing_in_target == 5 and s.join_keys == ["order_id"]
    assert s.schema_ok is False


def test_bi_metrics_mode_becomes_aggregate_findings():
    """AVF METRICS/BI mode (avf_validation_bi_results) -> AGGREGATE findings; PASS rows
    (within tolerance) are not surfaced."""
    findings, _, _ = ingest_avf(_runner(), "run1", RS)
    aggs = [f for f in findings if f.recon_type == ReconType.AGGREGATE]
    assert len(aggs) == 1                                  # only the FAIL metric
    assert aggs[0].column == "revenue"
    assert aggs[0].samples[0].source_value == 1000000.0
    assert aggs[0].metadata["source_system"] == "TERADATA"


def test_avf_source_autodetects_dialect():
    src = AVFSource("run1", RS)
    src.load(_runner())
    assert src.dialect == "teradata"


def test_avf_source_explicit_dialect_wins():
    src = AVFSource("run1", RS, dialect="oracle")
    src.load(_runner())
    assert src.dialect == "oracle"


def test_consume_rca_false_skips_rca_table():
    findings, _, _ = ingest_avf(_runner(), "run1", RS, consume_rca=False)
    vol = next(f for f in findings if f.recon_type == ReconType.MISSING_IN_TARGET)
    assert "avf_rca" not in vol.metadata


def test_attach_avf_rca_evidence():
    findings, _, _ = ingest_avf(_runner(), "run1", RS)
    vol = next(f for f in findings if f.recon_type == ReconType.MISSING_IN_TARGET)
    vol.hypotheses.append(Hypothesis(
        category=RootCauseCategory.VOLUME_MISSING, verdict=Verdict.NEEDS_REVIEW,
        confidence=0.5, rationale="x"))
    attach_avf_rca_evidence(findings)
    ev = [e for e in vol.top_hypothesis.evidence if e.label == "avf_rca"]
    assert ev and "FILTER_LOSS" in ev[0].detail
    assert ev[0].data["problematic_jobs"] == ["job_42"]


def test_empty_run_returns_nothing():
    findings, summaries, dialect = ingest_avf(_runner(avf_validation_summary=[]), "nope", RS)
    assert findings == [] and summaries == [] and dialect is None


def test_missing_avf_table_is_best_effort():
    class Boom(RoutingRunner):
        def query(self, sql):
            if "avf_validation_schema_mismatch" in sql:
                raise RuntimeError("table not found")
            return super().query(sql)

    r = Boom(avf_validation_summary=_SUMMARY, avf_validation_columns_mismatch=_COLS,
             avf_validation_rows_mismatch=_ROWS, avf_validation_rca=_RCA)
    findings, summaries, _ = ingest_avf(r, "run1", RS)
    assert summaries                       # ingest still produced the summary
    assert all(f.recon_type != ReconType.SCHEMA or not f.metadata.get("schema_diffs")
               for f in findings)


def test_analyze_with_avf_source_end_to_end():
    """analyze() routed through AVFSource: classify runs, dialect auto-applies, AVF RCA
    becomes evidence — all without live queries."""
    src = AVFSource("run1", RS)
    result = analyze(_runner(), "", "", "", source=src,
                     drilldown=False, drift=False, fixes=False,
                     validate_fixes=False, use_lineage=False, trace_job=False)
    assert result.recon_id == "run1"
    assert result.dialect == "teradata"
    assert result.findings
    vol = next(f for f in result.findings if f.recon_type == ReconType.MISSING_IN_TARGET)
    labels = [e.label for h in vol.hypotheses for e in h.evidence]
    assert "avf_rca" in labels


def test_analyze_default_is_lakebridge_source():
    """No source => LakebridgeSource built from the positional args; empty run => empty
    result with recon_id preserved (proves the default path is unchanged)."""
    class EmptyMain:
        def query(self, sql):
            return []
    result = analyze(EmptyMain(), "recon-xyz", "cat", "sch",
                     drilldown=False, drift=False, fixes=False, validate_fixes=False)
    assert result.recon_id == "recon-xyz"
    assert result.dialect == "snowflake"
    assert result.findings == []
    # sanity: the default really is a LakebridgeSource
    assert LakebridgeSource("recon-xyz", "cat", "sch").supports_aggregates is True
