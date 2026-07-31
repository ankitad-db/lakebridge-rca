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
    use_lineage: bool = False,
    only_table: str | None = None,
    drift: bool = True,
    blast_radius: bool | None = None,
    fixes: bool = True,
    validate_fixes: bool = True,
    memory: dict | None = None,
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
    - findings are then grouped into systemic ``clusters`` (one shared mechanism →
      many findings) so the report can lead with the single fix that clears the most.
    - ``fixes`` attaches a concrete, runnable suggested fix (corrected SQL / recon-config
      / back-fill) to each finding whose category has one; ``validate_fixes`` then runs
      each fix's validation query to mark it validated when the gap is fully explained by
      the mechanism the fix corrects.
    - ``memory`` (a ``{signature: MemoryHit}`` map from ``rca_engine.memory.load_memory``)
      applies learned priors from prior confirmed runs *before* the drill-down, so a
      recurring cause is proposed and then confirmed by a query (never on memory alone).
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
        findings = run_drilldown(findings, runner)
    if drift:
        from rca_engine.drift import run_drift
        findings = run_drift(findings, runner)
    if use_lineage:
        from rca_engine.lineage import run_lineage
        findings = run_lineage(findings, runner)
    if blast_radius is None:
        blast_radius = use_lineage
    if blast_radius:
        from rca_engine.lineage import run_blast_radius
        run_blast_radius(findings, summaries, runner)
    if fixes:
        from rca_engine.fixgen import generate_fixes
        findings = generate_fixes(findings)
        if validate_fixes and runner is not None:
            from rca_engine.fixgen import validate_all_fixes
            validate_all_fixes(findings, runner)

    from rca_engine.cluster import build_clusters
    clusters = build_clusters(findings)
    return RcaResult(recon_id=recon_id, dialect=dialect, findings=findings,
                     table_summaries=summaries, clusters=clusters)
