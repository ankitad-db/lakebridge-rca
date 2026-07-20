"""End-to-end RCA orchestration: ingest -> classify -> live drill-down.

One call that produces a concluded ``RcaResult`` with confirmed verdicts and
query-backed evidence, ready for the report/notebook.
"""

from __future__ import annotations

from rca_engine.classify import classify_all
from rca_engine.drilldown import run_drilldown
from rca_engine.ingest import QueryRunner, ingest
from rca_engine.models import RcaResult


def analyze(
    runner: QueryRunner,
    recon_id: str,
    recon_catalog: str,
    recon_schema: str,
    dialect: str = "snowflake",
    drilldown: bool = True,
) -> RcaResult:
    findings = ingest(runner, recon_id, recon_catalog, recon_schema)
    findings = classify_all(findings, dialect=dialect)
    if drilldown:
        findings = run_drilldown(findings, runner)
    return RcaResult(recon_id=recon_id, dialect=dialect, findings=findings)
