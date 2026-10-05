"""Validation-tool-agnostic ingest sources.

The RCA engine analyzes the OUTPUT of a validation tool. Historically that tool was
Lakebridge reconcile; this module makes the tool pluggable so the same deterministic +
query-gated engine runs on any validation tool's output. A ``ValidationSource`` loads one
run into the normalized model (``Finding`` / ``TableSummary``) and nothing downstream
(classify / drilldown / lineage / fixes / FM-fallback / report) needs to know which tool
produced it.

Design guarantee: ``analyze()`` defaults to :class:`LakebridgeSource`, which simply calls
the existing ``ingest_with_summaries`` — so the Lakebridge path is byte-for-byte unchanged.
Adding AVF (or any future tool) never touches that path.

Concrete sources:
- :class:`LakebridgeSource` — Lakebridge reconcile ``main``/``metrics``/``details`` by ``recon_id``.
- :class:`AVFSource` — AVF ``avf_*`` report tables by ``run_id`` (dialect auto-detected).
"""

from __future__ import annotations

from rca_engine.ingest import QueryRunner, ingest_with_summaries
from rca_engine.models import Finding, TableSummary


class ValidationSource:
    """Base class for a validation-tool ingest source.

    Subclasses set ``label`` (the run identity, used as ``RcaResult.recon_id``) and may set
    ``dialect`` (when the tool reports the source dialect, it overrides ``analyze()``'s
    default so the right knowledge base loads). ``load`` returns the normalized model.
    """

    label: str = ""
    dialect: str | None = None          # None => let analyze()'s dialect arg win
    supports_aggregates: bool = False   # whether aggregate-reconcile RCA applies

    def load(self, runner: QueryRunner, only_table: str | None = None
             ) -> tuple[list[Finding], list[TableSummary]]:
        raise NotImplementedError

    def aggregate_findings(self, runner: QueryRunner) -> list[Finding]:
        """Optional per-tool aggregate-reconcile findings (SUM/AVG/COUNT by group).
        Base: none."""
        return []

    def post_classify(self, findings: list[Finding], runner: QueryRunner | None = None) -> None:
        """Optional enrichment after classification (e.g. attach the tool's own RCA as
        evidence). Base: no-op."""
        return None


class LakebridgeSource(ValidationSource):
    """Lakebridge reconcile output — the original, unchanged ingest path."""

    supports_aggregates = True

    def __init__(self, recon_id: str, recon_catalog: str, recon_schema: str):
        self.label = recon_id
        self.recon_id = recon_id
        self.recon_catalog = recon_catalog
        self.recon_schema = recon_schema
        self.dialect = None   # caller's dialect arg governs the KB (unchanged behavior)

    def load(self, runner: QueryRunner, only_table: str | None = None
             ) -> tuple[list[Finding], list[TableSummary]]:
        return ingest_with_summaries(
            runner, self.recon_id, self.recon_catalog, self.recon_schema, only_table=only_table
        )

    def aggregate_findings(self, runner: QueryRunner) -> list[Finding]:
        from rca_engine.aggregate_rca import run_aggregate_rca
        return run_aggregate_rca(runner, self.recon_id, self.recon_catalog, self.recon_schema) or []


class AVFSource(ValidationSource):
    """AVF (Auto Validation Framework) output — reads the ``avf_*`` report tables for one
    ``run_id`` and emits the same normalized model. Dialect is auto-detected from
    ``avf_validation_summary.source_dialect`` unless an explicit ``dialect`` is given."""

    def __init__(self, run_id: str, reports_schema: str, dialect: str | None = None,
                 consume_rca: bool = True):
        self.label = run_id
        self.run_id = run_id
        self.reports_schema = reports_schema
        self.dialect = dialect           # explicit override; else set during load()
        self._explicit_dialect = dialect
        self.consume_rca = consume_rca

    def load(self, runner: QueryRunner, only_table: str | None = None
             ) -> tuple[list[Finding], list[TableSummary]]:
        from rca_engine.ingest_avf import ingest_avf
        findings, summaries, detected = ingest_avf(
            runner, self.run_id, self.reports_schema,
            only_table=only_table, consume_rca=self.consume_rca,
        )
        if not self._explicit_dialect and detected:
            self.dialect = detected
        return findings, summaries

    def post_classify(self, findings: list[Finding], runner: QueryRunner | None = None) -> None:
        if not self.consume_rca:
            return
        from rca_engine.ingest_avf import attach_avf_rca_evidence
        attach_avf_rca_evidence(findings)
