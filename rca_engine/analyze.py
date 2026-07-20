"""End-to-end RCA orchestration: ingest -> classify -> live drill-down.

One call that produces a concluded ``RcaResult`` with confirmed verdicts and
query-backed evidence, ready for the report/notebook.
"""

from __future__ import annotations

from rca_engine.classify import classify_all
from rca_engine.drilldown import run_drilldown
from rca_engine.ingest import QueryRunner, ingest_with_summaries
from rca_engine.models import RcaResult


def _apply_mapping(summaries, mapping: dict) -> None:
    """Overlay exact join keys / date column from Lakebridge artifacts onto the
    per-table summaries (replacing the heuristic guesses)."""

    for s in summaries:
        tm = mapping.get(s.target_table.split(".")[-1].strip("`").lower())
        if tm is None:
            continue
        if tm.join_keys:
            s.join_keys = tm.join_keys
        if tm.date_column:
            s.date_column = tm.date_column


def analyze(
    runner: QueryRunner,
    recon_id: str,
    recon_catalog: str,
    recon_schema: str,
    dialect: str = "snowflake",
    drilldown: bool = True,
    mapping: dict | None = None,
) -> RcaResult:
    findings, summaries = ingest_with_summaries(runner, recon_id, recon_catalog, recon_schema)
    if mapping:
        _apply_mapping(summaries, mapping)
    findings = classify_all(findings, dialect=dialect, mapping=mapping)
    if drilldown:
        findings = run_drilldown(findings, runner)
    return RcaResult(recon_id=recon_id, dialect=dialect, findings=findings, table_summaries=summaries)
