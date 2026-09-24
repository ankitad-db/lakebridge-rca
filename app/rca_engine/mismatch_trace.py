"""Job-level source-column trace — the SQL-derived *why* behind a value mismatch.

Reconciliation and the rest of the engine work at the **table** level: for a
source→target pair, which columns differ and by how much. When a target *column*
doesn't match, the next question is *which source column(s) it actually comes from
and how it is transformed* — and ETL renames and computes columns, so a filter that
reuses the target column name against a source table is meaningless (e.g.
``eff_routing_yield`` is ``EXP(SUM(LN(...)))`` over two different source columns, not
a column that exists in any source table).

This pass answers that at the **job** level. Given a mismatching target column it:

  1. finds the **job** that builds the target table from ``system.access.table_lineage``
     (the same system tables :mod:`rca_engine.lineage` already reads), or uses a
     caller-supplied ``job_id``;
  2. exports that job's notebook SQL via the Databricks SDK;
  3. parses the ETL SQL with **sqlglot** and walks the column's lineage down to its
     **true source ``table.column`` leaves**, capturing the transform at every hop; and
  4. builds a **runnable reproduction query** (the temp-object chain inlined as CTEs,
     restricted to the mismatching row) that recomputes the value from source.

It is complementary to :func:`rca_engine.lineage.run_lineage`: that walks UC
*metadata* lineage (which upstream tables/columns, and needs lineage to have been
captured); this parses the *actual ETL SQL* (how the value is computed, and works even
where UC column lineage is absent) and hands back a query you can run to see the raw
source inputs for the bad row.

Everything is optional and defensive — if sqlglot or the Databricks SDK is
unavailable, the job can't be resolved, or the target isn't built by the job's
notebooks, the pass attaches nothing and the RCA proceeds unaffected (same contract as
the UC-lineage pass).
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

from rca_engine.ingest import QueryRunner
from rca_engine.models import Evidence, Finding, ReconType, Verdict

try:  # sqlglot is optional; the whole pass is skipped if it's absent.
    import sqlglot
    from sqlglot import exp
    from sqlglot.lineage import lineage as _sqlglot_lineage

    _HAS_SQLGLOT = True
except Exception:  # pragma: no cover
    _HAS_SQLGLOT = False

DIALECT = "databricks"
DEFAULT_LOOKBACK_DAYS = 90


# --------------------------------------------------------------------------- #
# Parsed job model
# --------------------------------------------------------------------------- #
@dataclass
class JobSqlModel:
    """The lineage source-map for one job's notebook SQL.

    ``sources`` are DRILLABLE definitions (temp tables/views/CTAS) that ``lineage()``
    recurses into to reach real source columns; ``insert_targets`` are persisted tables
    built by ``INSERT INTO … SELECT`` (pipeline outputs, used only to locate a root, not
    drilled into); ``create_order`` is the creation order of temp objects (so an emitted
    CTE chain references only earlier objects)."""

    sources: dict[str, str] = field(default_factory=dict)
    insert_targets: dict[str, str] = field(default_factory=dict)
    create_order: list[str] = field(default_factory=list)
    parse_failures: int = 0

    def root_for(self, short_name: str) -> str | None:
        """The defining SELECT to start lineage from: a CREATE-built object if one
        exists, else the INSERT that builds this persisted table."""
        key = short_name.lower()
        return self.sources.get(key) or self.insert_targets.get(key)

    @property
    def built_names(self) -> set[str]:
        return set(self.sources) | set(self.insert_targets)


# --------------------------------------------------------------------------- #
# ${var} catalog-placeholder handling
# --------------------------------------------------------------------------- #
def substitute(text: str, edw_catalog: str = "") -> str:
    """Replace ``${var}`` placeholders so sqlglot can parse the identifiers. Use the
    catalog value if given, else a safe stand-in token mapped back on render."""

    def repl(m):
        var = m.group(1)
        return edw_catalog if edw_catalog else f"__sub_{var}__"

    return re.sub(r"\$\{([A-Za-z_]\w*)\}", repl, text)


def unsubstitute(text: str) -> str:
    return re.sub(r"__sub_([A-Za-z_]\w*)__", lambda m: "${" + m.group(1) + "}", text)


# --------------------------------------------------------------------------- #
# Parse notebook SQL into the lineage source-map
# --------------------------------------------------------------------------- #
def split_statements(src: str) -> list[str]:
    """Split notebook source into individual SQL statements.

    Splits on cell boundaries first, then lets sqlglot tokenize each cell into
    statements (so ``;`` inside string literals/comments is respected). Falls back to a
    naive ``;`` split only when a cell won't tokenize (e.g. a ``%python``/``%md`` magic
    cell), which the caller's ``parse_one`` skips anyway."""

    cells = re.split(r"(?m)^\s*--\s*COMMAND\s*-+\s*$", src)
    out: list[str] = []
    for c in cells:
        if not c.strip():
            continue
        stmts = None
        try:
            stmts = [s.sql(dialect=DIALECT) for s in sqlglot.parse(c, read=DIALECT) if s is not None]
        except Exception:
            stmts = None
        if stmts:
            out.extend(s for s in stmts if s.strip())
        else:
            out.extend(s.strip() for s in c.split(";") if s.strip())
    return out


def _qualified_name(node) -> str:
    """Fully-qualified dotted name (catalog.db.table) of a CREATE/INSERT target,
    reconstructed from the Table node's parts (``.name`` returns only the final
    identifier, but ``lineage()`` only drills a source key that matches the FROM ref)."""
    if node is None:
        return ""
    tbl = node if isinstance(node, exp.Table) else node.find(exp.Table)
    if tbl is None:
        return getattr(node, "name", "") or ""
    parts = [p for p in (tbl.catalog, tbl.db, tbl.name) if p]
    return ".".join(parts)


def _register(into: dict, name: str, select_sql: str) -> None:
    """Register ``name`` at every suffix depth (full 3-part, 2-part, and bare) so a FROM
    clause referencing the object by any of them matches a lineage key. LAST definition
    wins (a notebook may DROP+recreate a temp view; lineage must follow the one in
    effect when the target is built)."""
    if not name or not select_sql:
        return
    parts = name.lower().split(".")
    for i in range(len(parts)):
        into[".".join(parts[i:])] = select_sql


def build_source_map(notebook_sources: list[tuple[str, str, str]], edw_catalog: str = "") -> JobSqlModel:
    """Parse every notebook statement and register what the job builds — temp
    tables/views/CTAS as drillable ``sources`` and ``INSERT INTO … SELECT`` as
    ``insert_targets`` roots. ``notebook_sources`` is a list of ``(task_key, path,
    source_text)`` triples."""

    model = JobSqlModel()
    for _task, _path, raw in notebook_sources:
        for stmt in split_statements(substitute(raw, edw_catalog)):
            try:
                e = sqlglot.parse_one(stmt, read=DIALECT)
            except Exception:
                model.parse_failures += 1
                continue
            if e is None:
                continue
            if e.key == "create" and e.this is not None and e.expression is not None:
                nm = _qualified_name(e.this)
                _register(model.sources, nm, e.expression.sql(dialect=DIALECT))
                if nm:
                    short = nm.split(".")[-1].lower()
                    if short in model.create_order:
                        model.create_order.remove(short)
                    model.create_order.append(short)
            elif e.key == "insert" and e.this is not None and e.expression is not None:
                _register(model.insert_targets, _qualified_name(e.this), e.expression.sql(dialect=DIALECT))
    return model


# --------------------------------------------------------------------------- #
# Trace a column to its true source columns
# --------------------------------------------------------------------------- #
def _node_table(node, built_names: set[str]) -> str | None:
    """Best-effort source table for a lineage leaf node (prefer the AST, fall back to a
    regex over the rendered SQL)."""
    expr = node.expression
    if expr is not None:
        try:
            tables = list(expr.find_all(exp.Table)) if hasattr(expr, "find_all") else []
        except Exception:
            tables = []
        if tables:
            t = tables[0]
            parts = [p for p in (t.catalog, t.db, t.name) if p]
            if parts:
                return unsubstitute(".".join(parts))
    sql = expr.sql(dialect=DIALECT) if expr is not None else ""
    ident = r"(?:`[^`]+`|[A-Za-z_]\w*)"
    m = re.search(rf"({ident}\.{ident}(?:\.{ident})?)\s+AS\b", sql)
    if not m:
        m = re.search(rf"\bFROM\s+({ident}(?:\.{ident})*)", sql)
    return unsubstitute(m.group(1).replace("`", "")) if m else None


def _star_source_name(select_sql: str, sources: dict) -> str | None:
    """If ``select_sql`` is exactly ``SELECT * FROM <one table>`` (no joins), return that
    table's bare name (lowercased), else None."""
    try:
        e = sqlglot.parse_one(select_sql, read=DIALECT)
    except Exception:
        return None
    if not (
        isinstance(e, exp.Select)
        and len(e.selects) == 1
        and isinstance(e.selects[0], exp.Star)
        and not e.args.get("joins")
    ):
        return None
    tables = list(e.find_all(exp.Table))
    return tables[0].name.lower() if len(tables) == 1 else None


def _unwrap_star(root_sql: str, sources: dict) -> str:
    """Unwrap a ``SELECT * FROM final_output`` root to the underlying definition (which
    lists real columns) so lineage doesn't star-expand unrelated columns."""
    seen: set[str] = set()
    while True:
        tname = _star_source_name(root_sql, sources)
        if not tname or tname in seen or tname not in sources:
            break
        seen.add(tname)
        root_sql = sources[tname]
    return root_sql


def trace_column(col: str, root_sql: str, model: JobSqlModel) -> tuple[list[str], list[tuple[str, str | None, bool]]]:
    """Trace ``col`` (a projection of ``root_sql``) down to its source leaves.

    Returns ``(chain_lines, leaves)`` where ``chain_lines`` is the human-readable
    transform chain (one indented line per hop) and ``leaves`` is a list of
    ``(leaf_col, source_table, is_true_source)`` — ``is_true_source`` is True when the
    leaf's table is NOT built by the job (a real external source, not an intermediate)."""

    # Map a user-typed column to the actual alias casing used in the SELECT.
    try:
        parsed = sqlglot.parse_one(root_sql, read=DIALECT)
        aliases = {c.alias_or_name.lower(): c.alias_or_name for c in parsed.selects}
    except Exception:
        aliases = {}
    col_norm = aliases.get(col.lower(), col)

    tree = _sqlglot_lineage(col_norm, root_sql, sources=model.sources, dialect=DIALECT)
    built = model.built_names
    chain_lines: list[str] = []
    leaves: list[tuple[str, str | None, bool]] = []

    def walk(node, depth: int) -> None:
        expr = node.expression
        txt = expr.sql(dialect=DIALECT) if expr is not None else node.name
        chain_lines.append("    " * depth + f"{node.name}  <=  {unsubstitute(txt)[:90]}")
        if not node.downstream:
            tbl = _node_table(node, built)
            short = tbl.split(".")[-1].lower() if tbl else ""
            is_source = tbl is not None and short not in built
            leaves.append((node.name, tbl, is_source))
        for d in node.downstream:
            walk(d, depth + 1)

    walk(tree, 0)
    return chain_lines, leaves


# --------------------------------------------------------------------------- #
# Reproduction query (recompute the bad row from source)
# --------------------------------------------------------------------------- #
def _build_cte_chain(root_name: str, model: JobSqlModel) -> tuple[str, list[str]]:
    """Return ``(with_prefix, ordered_names)`` for the transitive closure of CREATE-built
    temp objects ``root_name`` depends on, in creation order (each CTE references only
    earlier ones)."""

    def temp_refs(select_sql: str) -> set[str]:
        try:
            p = sqlglot.parse_one(select_sql, read=DIALECT)
        except Exception:
            return set()
        local_ctes = {c.alias_or_name.lower() for c in p.find_all(exp.CTE)}
        out: set[str] = set()
        for t in p.find_all(exp.Table):
            nm = t.name.lower()
            if nm in model.sources and nm not in local_ctes and t.catalog == "" and t.db == "":
                out.add(nm)
        return out

    need: set[str] = set()
    stack = [root_name.lower()]
    while stack:
        n = stack.pop()
        if n in need or n not in model.sources:
            continue
        need.add(n)
        for r in temp_refs(model.sources[n]):
            if r not in need:
                stack.append(r)
    ordered = [n for n in model.create_order if n in need]
    if root_name.lower() not in ordered and root_name.lower() in model.sources:
        ordered.append(root_name.lower())
    if not ordered:
        return "", []
    ctes = ",\n".join(f"  {n} AS (\n{model.sources[n]}\n  )" for n in ordered)
    return f"WITH\n{ctes}\n", ordered


def build_reproduction_query(root_name: str, row_filter: str, model: JobSqlModel) -> str:
    """The temp-object closure inlined as CTEs + ``SELECT * FROM root_name`` restricted to
    the mismatching row — recomputes the value from source. Empty if there is no chain."""
    with_prefix, ordered = _build_cte_chain(root_name, model)
    if not ordered:
        return ""
    q = f"{with_prefix}SELECT * FROM {root_name}"
    if row_filter:
        q += f"\nWHERE {row_filter}"
    return unsubstitute(q)


# --------------------------------------------------------------------------- #
# Job discovery + notebook export
# --------------------------------------------------------------------------- #
def resolve_job_for_table(
    runner: QueryRunner, target_table: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> str | None:
    """The job that builds ``target_table``, from ``system.access.table_lineage`` (the
    producing ``entity_id`` where ``entity_type = 'JOB'``). Returns the most frequent job
    id, or None when lineage is unavailable / no job produced the table."""
    try:
        rows = runner.query(
            "SELECT entity_id AS job_id, COUNT(*) AS n "
            "FROM system.access.table_lineage "
            f"WHERE lower(target_table_full_name) = lower('{target_table}') "
            "AND entity_type = 'JOB' AND entity_id IS NOT NULL "
            f"AND event_date >= current_date() - INTERVAL {int(lookback_days)} DAYS "
            "GROUP BY entity_id ORDER BY n DESC"
        )
    except Exception:
        return None
    for r in rows:
        jid = r.get("job_id")
        if jid:
            return str(jid)
    return None


def export_job_sql(job_id: str, ws) -> list[tuple[str, str, str]]:
    """Export each notebook task's SQL source for ``job_id`` as ``(task_key, path,
    source_text)``. Non-notebook tasks (SQL-file, dbt, wheel, …) are skipped — the tracer
    reads notebook SQL only. Defensive: returns [] on any SDK error."""
    try:
        from databricks.sdk.service.workspace import ExportFormat
    except Exception:
        return []
    settings = None
    try:
        if str(job_id).isdigit():
            settings = ws.jobs.get(int(job_id)).settings
        else:
            for j in ws.jobs.list(name=str(job_id)):
                settings = ws.jobs.get(j.job_id).settings
                break
    except Exception:
        return []
    if settings is None:
        return []
    out: list[tuple[str, str, str]] = []
    for t in settings.tasks or []:
        nb = getattr(t, "notebook_task", None)
        if not nb:
            continue
        try:
            exported = ws.workspace.export(path=nb.notebook_path, format=ExportFormat.SOURCE)
            src = base64.b64decode(exported.content).decode("utf-8", errors="replace")
            out.append((t.task_key, nb.notebook_path, src))
        except Exception:
            continue
    return out


def _get_workspace_client(profile: str | None = None):
    """Build a ``WorkspaceClient`` (profile for local CLI runs; default auth inside a
    notebook). Returns None if the SDK is unavailable or auth can't be established."""
    try:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Helpers for the pass
# --------------------------------------------------------------------------- #
def _row_filter_from_finding(f: Finding) -> str:
    """A SQL predicate identifying one mismatching row, built from the first sample's
    join keys (``col = value`` AND-joined). Empty when the finding has no sampled row."""
    if not f.samples:
        return ""
    keys = f.samples[0].keys or {}
    parts: list[str] = []
    for k, v in keys.items():
        if v is None:
            parts.append(f"{k} IS NULL")
        elif isinstance(v, bool):
            parts.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, (int, float)):
            parts.append(f"{k} = {v}")
        else:
            parts.append("{} = '{}'".format(k, str(v).replace("'", "''")))
    return " AND ".join(parts)


def _true_source_labels(leaves: list[tuple[str, str | None, bool]]) -> list[str]:
    """Distinct ``table.column`` labels for the leaves that are real external sources."""
    out: list[str] = []
    for leaf_col, tbl, ok in leaves:
        if ok and tbl:
            label = f"`{tbl}.{leaf_col.split('.')[-1]}`"
            if label not in out:
                out.append(label)
    return out


# --------------------------------------------------------------------------- #
# The pass
# --------------------------------------------------------------------------- #
def run_mismatch_trace(
    findings: list[Finding],
    runner: QueryRunner,
    ws=None,
    job_id: str | None = None,
    profile: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    edw_catalog: str = "",
) -> list[Finding]:
    """Attach a job-level ETL-SQL source trace to each actionable column-mismatch finding.

    For each target table it resolves the building job (``job_id`` override, else
    ``system.access.table_lineage``), exports and parses the job's notebook SQL once, then
    for each ``COLUMN_MISMATCH`` finding whose top hypothesis is actionable
    (migration-induced / needs-review) traces the mismatching column to its true source
    columns and builds a reproduction query for the sampled row. Every step is
    best-effort: any failure skips that finding and attaches nothing."""

    if not _HAS_SQLGLOT or not findings:
        return findings

    if ws is None:
        ws = _get_workspace_client(profile)
    if ws is None:
        return findings

    by_table: dict[str, list[Finding]] = {}
    for f in findings:
        by_table.setdefault(f.target_table, []).append(f)

    job_cache: dict[str, JobSqlModel] = {}  # job_id -> parsed model (export/parse once)

    for table, fs in by_table.items():
        col_findings = [
            f
            for f in fs
            if f.recon_type == ReconType.COLUMN_MISMATCH
            and f.column
            and f.top_hypothesis is not None
            and f.top_hypothesis.verdict in (Verdict.MIGRATION_INDUCED, Verdict.NEEDS_REVIEW)
        ]
        if not col_findings:
            continue

        jid = job_id or resolve_job_for_table(runner, table, lookback_days=lookback_days)
        if not jid:
            continue

        model = job_cache.get(jid)
        if model is None:
            notebook_sources = export_job_sql(jid, ws)
            if not notebook_sources:
                job_cache[jid] = JobSqlModel()  # remember the miss; don't re-export
                continue
            model = build_source_map(notebook_sources, edw_catalog=edw_catalog)
            job_cache[jid] = model
        if not model.sources and not model.insert_targets:
            continue

        tgt_short = table.split(".")[-1].strip("`[] ")
        root = model.root_for(tgt_short)
        if root is None:
            continue  # this job's notebooks don't build the target
        root_sql = _unwrap_star(root, model.sources)

        # The reproduction root: fall back to the star's underlying object name.
        root_name = tgt_short
        star_name = _star_source_name(root, model.sources)
        if star_name and star_name in model.sources:
            root_name = star_name

        for f in col_findings:
            try:
                chain, leaves = trace_column(f.column, root_sql, model)
            except Exception:
                continue
            src_labels = _true_source_labels(leaves)
            if not src_labels and not chain:
                continue

            row_filter = _row_filter_from_finding(f)
            try:
                repro = build_reproduction_query(root_name, row_filter, model)
            except Exception:
                repro = ""

            if src_labels:
                detail = (
                    f"ETL source trace (job `{jid}`): `{f.column}` is built from "
                    + ", ".join(src_labels)
                    + ". Compare the target value against these real source column(s); "
                    "then run the reproduction query to recompute the value from source for "
                    "the sampled row."
                )
            else:
                detail = (
                    f"ETL source trace (job `{jid}`): `{f.column}` resolved to no external "
                    "source column (it may be a constant/derived value or the lineage stopped "
                    "at an intermediate the job rebuilds). See the transform chain."
                )

            f.top_hypothesis.evidence.append(
                Evidence(
                    label="source_trace",
                    detail=detail,
                    query=repro or None,
                    data={
                        "job_id": jid,
                        "true_source_columns": src_labels,
                        "chain": chain,
                        "leaves": [
                            {"column": lc, "table": tb, "is_true_source": ok} for lc, tb, ok in leaves
                        ],
                        "row_filter": row_filter,
                    },
                )
            )
    return findings
