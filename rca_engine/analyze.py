"""End-to-end RCA orchestration: ingest -> classify -> live drill-down.

One call that produces a concluded ``RcaResult`` with confirmed verdicts and
query-backed evidence, ready for the report/notebook.
"""

from __future__ import annotations

from rca_engine.classify import classify_all
from rca_engine.drilldown import run_drilldown
from rca_engine.ingest import QueryRunner, ingest_with_summaries
from rca_engine.models import RcaResult
from rca_engine.scan import ScanScope


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
    use_lineage: bool = False,
    max_lineage_hops: int = 10,
    trace_job: bool = False,
    job_id: str | None = None,
    profile: str | None = None,
    only_table: str | None = None,
    drift: bool = True,
    blast_radius: bool | None = None,
    fixes: bool = True,
    validate_fixes: bool = True,
    memory: dict | None = None,
    scope: ScanScope | None = None,
) -> RcaResult:
    """Run the end-to-end RCA for a recon run.

    ``only_table`` scopes the analysis to a single table pair (one-table-at-a-time);
    leave ``None`` to analyze the whole run.

    Post-drill-down enrichment (all live, all defensive):
    - ``drift`` quantifies each column's source-vs-target distribution shift
      (null-rate / cardinality / numeric summary), sharpening migration-vs-genuine.
    - ``blast_radius`` records the downstream tables that consume each *affected*
      target, so a fix can be prioritized by how far the defect propagates. Defaults
      to ``use_lineage`` (both read the UC ``system.access`` tables).
    - when ``use_lineage`` is on, each finding also gets a **depth-agnostic upstream
      trace-back**: lineage is walked hop by hop (column lineage where a column is known,
      table lineage otherwise) to the root layer, so a defect that entered several layers
      upstream is pointed at directly. ``max_lineage_hops`` bounds the walk depth.
    - ``trace_job`` adds a **job-level source-column trace**: for each actionable column
      mismatch it finds the job that builds the target (from ``system.access.table_lineage``,
      or the supplied ``job_id``), parses the job's ETL SQL with sqlglot, walks the column
      back to its *true source columns* (the transform at every hop), and attaches a runnable
      reproduction query that recomputes the value from source for the sampled row. It
      complements ``use_lineage`` (UC metadata) with the actual SQL-derived "why".
      ``profile`` is used to build the Databricks SDK client for local CLI runs.
    - findings are then grouped into systemic ``clusters`` (one shared mechanism →
      many findings) so the report can lead with the single fix that clears the most.
    - ``fixes`` attaches a concrete, runnable suggested fix (corrected SQL / recon-config
      / back-fill) to each finding whose category has one; ``validate_fixes`` then runs
      each fix's validation query to mark it validated when the gap is fully explained by
      the mechanism the fix corrects.
    - ``memory`` (a ``{signature: MemoryHit}`` map from ``rca_engine.memory.load_memory``)
      applies learned priors from prior confirmed runs *before* the drill-down, so a
      recurring cause is proposed and then confirmed by a query (never on memory alone).
    - ``scope`` (:class:`rca_engine.scan.ScanScope`) bounds the live confirming, drift, and
      fix-validation queries so they don't full-scan the source/target: ``"scoped"`` binds
      column confirms to the reconciliation-flagged keys and restricts full-table
      aggregates to a partition/date window; ``"full"`` (or ``None``) keeps the original
      unbounded scans.
    """

    findings, summaries = ingest_with_summaries(
        runner, recon_id, recon_catalog, recon_schema, only_table=only_table
    )
    if mapping:
        _apply_mapping(summaries, mapping)
    findings = classify_all(findings, dialect=dialect, mapping=mapping)
    if memory:
        from rca_engine.memory import apply_memory
        findings = apply_memory(findings, memory, dialect)
    if drilldown:
        findings = run_drilldown(findings, runner, scope)
    if drift:
        from rca_engine.drift import run_drift
        findings = run_drift(findings, runner, scope)
    if use_lineage:
        from rca_engine.lineage import run_lineage
        findings = run_lineage(findings, runner, max_hops=max_lineage_hops)
    if trace_job:
        from rca_engine.mismatch_trace import run_mismatch_trace
        findings = run_mismatch_trace(findings, runner, job_id=job_id, profile=profile)
    if blast_radius is None:
        blast_radius = use_lineage
    if blast_radius:
        from rca_engine.lineage import run_blast_radius
        run_blast_radius(findings, summaries, runner)
    if fixes:
        from rca_engine.fixgen import generate_fixes
        findings = generate_fixes(findings, scope)
        if validate_fixes and runner is not None:
            from rca_engine.fixgen import validate_all_fixes
            validate_all_fixes(findings, runner)

    # Aggregate-reconcile RCA (feature #13): if this recon_id is an aggregates-reconcile
    # run, ingest its per-rule aggregate mismatches (SUM/AVG/COUNT/... by group) and append
    # them. Best-effort — never breaks the row-level RCA.
    if runner is not None:
        try:
            from rca_engine.aggregate_rca import run_aggregate_rca
            from rca_engine.models import TableSummary
            agg = run_aggregate_rca(runner, recon_id, recon_catalog, recon_schema)
            if agg:
                findings = list(findings) + agg
                have = {s.target_table for s in summaries}
                for f in agg:
                    if f.target_table and f.target_table not in have:
                        summaries.append(TableSummary(source_table=f.source_table,
                                                      target_table=f.target_table))
                        have.add(f.target_table)
        except Exception:
            pass

    from rca_engine.cluster import build_clusters
    clusters = build_clusters(findings)
    return RcaResult(recon_id=recon_id, dialect=dialect, findings=findings,
                     table_summaries=summaries, clusters=clusters)
