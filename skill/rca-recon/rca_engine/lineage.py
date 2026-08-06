"""Optional Unity Catalog lineage evidence.

When enabled (and UC lineage has been captured for the target tables), this adds an
independent confirmation source to the RCA: column-level lineage shows a target
column's *true* upstream column(s), and table lineage shows the upstream tables that
feed a target — useful for volume/drift findings (where was a filter/join introduced?)
and for catching an unexpected provenance (a column sourced from a table other than the
one being reconciled).

Trace-back is **depth-agnostic**: from the reconciled target it walks upstream hop by
hop — following *column* lineage when a column is known, *table* lineage otherwise —
until it reaches the roots (tables with no further upstream) or exhausts a safety
budget (``max_hops`` / ``max_paths``). So a defect introduced N layers back (e.g. in an
intermediate staging/transform table) is surfaced as a full path from the target to the
layer where the difference entered, regardless of how many layers there are.

It reads the ``system.access.column_lineage`` / ``system.access.table_lineage`` system
tables through the same ``QueryRunner`` the rest of the engine uses. Every query is
defensive: if the system tables are unavailable, empty, or access is denied, the pass
attaches nothing and the RCA proceeds unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rca_engine.ingest import QueryRunner
from rca_engine.models import Evidence, Finding, ReconType, TableSummary, Verdict

DEFAULT_MAX_HOPS = 10
DEFAULT_MAX_PATHS = 8


@dataclass
class LineageInfo:
    upstream_tables: list[str] = field(default_factory=list)
    column_upstreams: dict[str, list[str]] = field(default_factory=dict)  # target_col -> [source_col fqn]


@dataclass
class LineageNode:
    table: str
    column: str | None = None

    def label(self) -> str:
        return f"`{self.table}.{self.column}`" if self.column else f"`{self.table}`"

    def key(self) -> tuple[str, str]:
        return (self.table.lower(), (self.column or "").lower())


@dataclass
class LineageChain:
    """The full upstream trace-back for one target table/column.

    ``paths`` is a list of root-paths, each an ordered list of :class:`LineageNode`
    from the reconciled target (index 0) back to a root (last index). ``truncated`` is
    True when the walk hit the ``max_hops``/``max_paths`` budget before reaching every
    root (so the chain may be incomplete)."""

    target: LineageNode
    paths: list[list[LineageNode]] = field(default_factory=list)
    truncated: bool = False

    @property
    def max_depth(self) -> int:
        return max((len(p) - 1 for p in self.paths), default=0)

    def root_tables(self) -> list[str]:
        return sorted({p[-1].table for p in self.paths if len(p) > 1})

    def format_paths(self, limit: int = 4) -> list[str]:
        out = []
        for p in self.paths[:limit]:
            if len(p) < 2:
                continue
            out.append(" ← ".join(n.label() for n in p))
        return out


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`").lower() if name else ""


def _column_parents(
    runner: QueryRunner, table: str, column: str, lookback_days: int, cache: dict
) -> list[tuple[str, str]]:
    """Direct (one-hop) column parents of ``table.column`` from UC column lineage."""

    ck = ("col", table.lower(), (column or "").lower())
    if ck in cache:
        return cache[ck]
    parents: list[tuple[str, str]] = []
    try:
        rows = runner.query(
            "SELECT DISTINCT source_table_full_name AS src_tbl, source_column_name AS src_col "
            "FROM system.access.column_lineage "
            f"WHERE lower(target_table_full_name) = lower('{table}') "
            f"AND lower(target_column_name) = lower('{column}') "
            "AND source_table_full_name IS NOT NULL AND source_column_name IS NOT NULL "
            f"AND event_date >= current_date() - INTERVAL {int(lookback_days)} DAYS"
        )
        for r in rows:
            st, sc = r.get("src_tbl"), r.get("src_col")
            if st and sc:
                parents.append((str(st), str(sc)))
    except Exception:
        parents = []
    cache[ck] = parents
    return parents


def _table_parents(
    runner: QueryRunner, table: str, lookback_days: int, cache: dict
) -> list[str]:
    """Direct (one-hop) table parents of ``table`` from UC table lineage."""

    ck = ("tbl", table.lower())
    if ck in cache:
        return cache[ck]
    parents: list[str] = []
    try:
        rows = runner.query(
            "SELECT DISTINCT source_table_full_name AS src_tbl "
            "FROM system.access.table_lineage "
            f"WHERE lower(target_table_full_name) = lower('{table}') "
            "AND source_table_full_name IS NOT NULL "
            f"AND lower(source_table_full_name) <> lower('{table}') "
            f"AND event_date >= current_date() - INTERVAL {int(lookback_days)} DAYS"
        )
        parents = sorted({str(r.get("src_tbl")) for r in rows if r.get("src_tbl")})
    except Exception:
        parents = []
    cache[ck] = parents
    return parents


def fetch_lineage(runner: QueryRunner, target_table: str, lookback_days: int = 90) -> LineageInfo:
    """One-hop upstream of ``target_table`` (columns + tables). Kept for callers that
    only need the immediate provenance (e.g. the LLM evidence bundle)."""

    info = LineageInfo()
    try:
        rows = runner.query(
            "SELECT source_table_full_name AS src_tbl, source_column_name AS src_col, "
            "target_column_name AS tgt_col "
            "FROM system.access.column_lineage "
            f"WHERE lower(target_table_full_name) = lower('{target_table}') "
            "AND source_table_full_name IS NOT NULL "
            f"AND event_date >= current_date() - INTERVAL {int(lookback_days)} DAYS "
            "GROUP BY 1, 2, 3"
        )
        for r in rows:
            tgt_col = str(r.get("tgt_col") or "").lower()
            src_tbl, src_col = r.get("src_tbl"), r.get("src_col")
            if src_tbl:
                info.upstream_tables.append(str(src_tbl))
            if tgt_col and src_tbl and src_col:
                info.column_upstreams.setdefault(tgt_col, []).append(f"{src_tbl}.{src_col}")
    except Exception:
        pass
    if not info.upstream_tables:
        try:
            rows = runner.query(
                "SELECT DISTINCT source_table_full_name AS src_tbl "
                "FROM system.access.table_lineage "
                f"WHERE lower(target_table_full_name) = lower('{target_table}') "
                "AND source_table_full_name IS NOT NULL "
                f"AND event_date >= current_date() - INTERVAL {int(lookback_days)} DAYS"
            )
            info.upstream_tables = [str(r.get("src_tbl")) for r in rows if r.get("src_tbl")]
        except Exception:
            pass
    info.upstream_tables = sorted(set(info.upstream_tables))
    return info


def trace_upstream(
    runner: QueryRunner,
    target_table: str,
    column: str | None = None,
    *,
    max_hops: int = DEFAULT_MAX_HOPS,
    max_paths: int = DEFAULT_MAX_PATHS,
    lookback_days: int = 90,
    cache: dict | None = None,
) -> LineageChain:
    """Walk UC lineage upstream from ``target_table`` (following column lineage when a
    ``column`` is given, else table lineage) all the way to the roots, or until the
    ``max_hops`` depth / ``max_paths`` breadth budget is hit.

    Cycle-safe (a node already on the current path is not re-expanded) and query-cached
    (each ``(table, column)`` parent lookup runs at most once per call). Returns a
    :class:`LineageChain` of root-paths from the target back to where lineage ends.
    """

    cache = cache if cache is not None else {}
    root = LineageNode(target_table, column)
    chain = LineageChain(target=root)

    def dfs(path: list[LineageNode]) -> None:
        if len(chain.paths) >= max_paths:
            chain.truncated = True
            return
        node = path[-1]
        if len(path) - 1 >= max_hops:
            chain.truncated = True
            chain.paths.append(path)  # record the (budget-truncated) path so far
            return
        if node.column:
            parents = [LineageNode(t, c) for (t, c) in
                       _column_parents(runner, node.table, node.column, lookback_days, cache)]
        else:
            parents = [LineageNode(t, None) for t in
                       _table_parents(runner, node.table, lookback_days, cache)]
        on_path = {n.key() for n in path}
        parents = [p for p in parents if p.key() not in on_path]  # break cycles
        if not parents:
            chain.paths.append(path)  # reached a root
            return
        for p in parents:
            if len(chain.paths) >= max_paths:
                chain.truncated = True
                break
            dfs(path + [p])

    dfs([root])
    return chain


def run_lineage(
    findings: list[Finding],
    runner: QueryRunner,
    lookback_days: int = 90,
    max_hops: int = DEFAULT_MAX_HOPS,
) -> list[Finding]:
    """Attach UC-lineage evidence to findings: the immediate upstream (provenance +
    surprise check) *and* a depth-agnostic trace-back path to the root layer, so a
    defect that entered several layers upstream is pointed at directly."""

    by_table: dict[str, list[Finding]] = {}
    for f in findings:
        by_table.setdefault(f.target_table, []).append(f)

    cache: dict = {}  # shared across all findings in this run — one query per node
    for table, fs in by_table.items():
        info = fetch_lineage(runner, table, lookback_days=lookback_days)
        expected_src = _short(fs[0].source_table) if fs else ""
        for f in fs:
            top = f.top_hypothesis
            if top is None:
                continue

            if f.recon_type == ReconType.COLUMN_MISMATCH and f.column:
                ups = info.column_upstreams.get(f.column.lower())
                if ups:
                    top.evidence.append(Evidence(
                        label="lineage",
                        detail=f"UC column lineage: `{f.column}` derives from {ups}.",
                    ))
                    if (expected_src and len(ups) == 1
                            and not any(expected_src in u.lower() for u in ups)):
                        top.evidence.append(Evidence(
                            label="lineage",
                            detail=f"Lineage shows `{f.column}` is sourced from `{ups[0]}`, not the "
                            f"reconciled source `{fs[0].source_table}` — check for an unexpected "
                            f"join/derivation.",
                        ))
                # Full trace-back to the root layer (multi-hop).
                chain = trace_upstream(
                    runner, table, f.column, max_hops=max_hops, lookback_days=lookback_days, cache=cache
                )
                _attach_chain(top, chain)

            elif f.recon_type in (ReconType.MISSING_IN_TARGET, ReconType.MISSING_IN_SOURCE):
                if info.upstream_tables:
                    top.evidence.append(Evidence(
                        label="lineage",
                        detail=f"UC table lineage: target is fed by {info.upstream_tables}. Inspect the "
                        f"upstream job/query for the filter/join that changed row volume.",
                    ))
                chain = trace_upstream(
                    runner, table, None, max_hops=max_hops, lookback_days=lookback_days, cache=cache
                )
                _attach_chain(top, chain)
    return findings


def _attach_chain(top, chain: LineageChain) -> None:
    """Attach a readable multi-hop trace-back to the hypothesis (only if it went past
    the first hop, since the one-hop provenance is already recorded above)."""

    if chain.max_depth < 2:
        return
    paths = chain.format_paths()
    if not paths:
        return
    roots = chain.root_tables()
    trunc = " (budget-truncated; increase max_lineage_hops for the full path)" if chain.truncated else ""
    detail = (
        f"Lineage trace-back ({chain.max_depth} hops to "
        f"{'root(s) ' + ', '.join('`' + r + '`' for r in roots) if roots else 'the deepest layer reached'}): "
        + "; ".join(paths)
        + ". The difference may have entered at an intermediate layer — inspect the upstream "
        "transform/table on the path, not only the reconciled target." + trunc
    )
    top.evidence.append(Evidence(
        label="lineage",
        detail=detail,
        data={
            "trace_paths": [[{"table": n.table, "column": n.column} for n in p] for p in chain.paths],
            "roots": roots,
            "max_depth": chain.max_depth,
            "truncated": chain.truncated,
        },
    ))


def fetch_downstream(runner: QueryRunner, target_table: str, lookback_days: int = 90) -> list[str]:
    """Tables that *consume* ``target_table`` (it is the source in table lineage) —
    i.e. the blast radius of a defect landing in this table. Defensive: returns []
    when the system tables are unavailable."""

    try:
        rows = runner.query(
            "SELECT DISTINCT target_table_full_name AS tgt "
            "FROM system.access.table_lineage "
            f"WHERE lower(source_table_full_name) = lower('{target_table}') "
            "AND target_table_full_name IS NOT NULL "
            f"AND lower(target_table_full_name) <> lower('{target_table}') "
            f"AND event_date >= current_date() - INTERVAL {int(lookback_days)} DAYS"
        )
        return sorted({str(r.get("tgt")) for r in rows if r.get("tgt")})
    except Exception:
        return []


def run_blast_radius(
    findings: list[Finding],
    summaries: list[TableSummary],
    runner: QueryRunner,
    lookback_days: int = 90,
) -> None:
    """Record each affected table's downstream consumers so the report can prioritize
    fixes by how far a defect propagates.

    Only tables carrying an *actionable* finding (a migration-induced defect or a
    needs-review) are probed — a benign/expected difference has no blast radius worth
    escalating. The downstream list is stored on the matching ``TableSummary`` and, for
    the worst finding on the table, added as an evidence line."""

    actionable_tables = {
        f.target_table
        for f in findings
        if f.top_hypothesis
        and f.top_hypothesis.verdict in (Verdict.MIGRATION_INDUCED, Verdict.NEEDS_REVIEW)
    }
    summary_by_table = {s.target_table: s for s in summaries}

    for table in actionable_tables:
        downstream = fetch_downstream(runner, table, lookback_days=lookback_days)
        if not downstream:
            continue
        s = summary_by_table.get(table)
        if s is not None:
            s.downstream_tables = downstream
        # Attach the blast-radius note to the highest-mismatch finding on this table.
        tbl_findings = [f for f in findings if f.target_table == table and f.top_hypothesis]
        if tbl_findings:
            worst = max(tbl_findings, key=lambda f: f.mismatch_count)
            preview = ", ".join(f"`{t}`" for t in downstream[:5])
            more = f" (+{len(downstream) - 5} more)" if len(downstream) > 5 else ""
            worst.top_hypothesis.evidence.append(Evidence(
                label="lineage",
                detail=f"Blast radius: {len(downstream)} downstream table(s) consume this table "
                f"({preview}{more}); a defect here propagates — prioritize the fix and "
                f"re-validate consumers.",
                data={"downstream_tables": downstream, "downstream_count": len(downstream)},
            ))
