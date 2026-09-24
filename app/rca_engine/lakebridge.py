"""Consume Lakebridge workflow artifacts to make the RCA code-aware.

RCA is the step *after* Lakebridge transpile + reconcile. This module ingests the
upstream Lakebridge artifacts so the classifier can confirm a mismatch's cause at
the code level instead of inferring it from values alone:

  * recon config (JSON)      -> exact join keys, column mapping, filters per pair.
  * transpile output folder  -> converted Databricks SQL; parsed (sqlglot) into a
                                per-target-column transform (expression + functions,
                                or "direct passthrough").
  * transpile error report   -> Lakebridge's own flagged/failed translations
                                (TranspileError lines), a direct transpilation signal.

Everything is optional and defensive: if sqlglot is unavailable or an artifact is
missing, the engine falls back to the data-driven RCA with no error.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:  # sqlglot is optional; code-correlation is skipped if it's absent.
    import sqlglot
    from sqlglot import exp

    _HAS_SQLGLOT = True
except Exception:  # pragma: no cover
    _HAS_SQLGLOT = False

_DATE_RE = re.compile(r"(date|dt|_ts|timestamp|time|day|month|year)", re.IGNORECASE)


@dataclass
class ColumnTransform:
    target_column: str
    expr: str = ""
    functions: list[str] = field(default_factory=list)
    is_direct: bool = False  # plain column reference / passthrough (cannot be transpilation)
    source_file: str = ""     # migrated-SQL file this derivation was parsed from


@dataclass
class TranspileIssue:
    path: str
    kind: str
    severity: str
    message: str
    line: Optional[int] = None


@dataclass
class TableMapping:
    source_table: str = ""
    target_table: str = ""
    join_keys: list[str] = field(default_factory=list)
    date_column: Optional[str] = None
    column_map: dict[str, str] = field(default_factory=dict)     # source_col -> target_col
    transforms: dict[str, ColumnTransform] = field(default_factory=dict)  # by target column
    source_types: dict[str, str] = field(default_factory=dict)   # source col (lower) -> declared type
    source_filter: str = ""
    target_filter: str = ""
    from_sql: str = ""   # the target SELECT's FROM + JOINs (so joined lookup tables are known)
    transpile_issues: list[TranspileIssue] = field(default_factory=list)
    # --- extra Lakebridge reconcile-config features (customize what/how recon compares) ---
    recon_transforms: dict[str, dict[str, str]] = field(default_factory=dict)  # col(lower) -> {source, target}
    column_thresholds: dict[str, dict[str, str]] = field(default_factory=dict)  # col(lower) -> {lower,upper,type}
    table_thresholds: list[dict] = field(default_factory=list)
    select_columns: list[str] = field(default_factory=list)
    drop_columns: list[str] = field(default_factory=list)
    jdbc_reader_options: dict = field(default_factory=dict)

    def transform_for(self, target_col: str) -> Optional[ColumnTransform]:
        return self.transforms.get(target_col)

    def source_type_of(self, col: str) -> Optional[str]:
        return self.source_types.get(col.lower()) if col else None

    def recon_transform_for(self, col: str) -> Optional[dict[str, str]]:
        return self.recon_transforms.get(col.lower()) if col else None

    def threshold_for(self, col: str) -> Optional[dict[str, str]]:
        return self.column_thresholds.get(col.lower()) if col else None


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`").lower() if name else ""


# --------------------------------------------------------------------------- #
# recon config
# --------------------------------------------------------------------------- #
def load_recon_config(path: str | Path) -> dict[str, TableMapping]:
    """Parse a Lakebridge reconcile config JSON into per-target-table mappings."""

    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    out: dict[str, TableMapping] = {}
    for t in data.get("tables", []):
        src = t.get("source_name", "")
        tgt = t.get("target_name", src)
        col_map = {c.get("source_name"): c.get("target_name")
                   for c in (t.get("column_mapping") or []) if c.get("source_name")}
        filters = t.get("filters") or {}
        keys = list(t.get("join_columns") or [])
        recon_transforms = {
            (tr.get("column_name") or "").lower(): {"source": tr.get("source") or "",
                                                    "target": tr.get("target") or ""}
            for tr in (t.get("transformations") or []) if tr.get("column_name")
        }
        col_thresholds = {
            (th.get("column_name") or "").lower(): {
                "lower": str(th.get("lower_bound", "")),
                "upper": str(th.get("upper_bound", "")),
                "type": th.get("type", ""),
            }
            for th in (t.get("column_thresholds") or []) if th.get("column_name")
        }
        out[_short(tgt)] = TableMapping(
            source_table=src,
            target_table=tgt,
            join_keys=keys,
            date_column=_DATE_RE.search(" ".join(keys)) and next((k for k in keys if _DATE_RE.search(k)), None),
            column_map=col_map,
            source_filter=(filters.get("source") or ""),
            target_filter=(filters.get("target") or ""),
            recon_transforms=recon_transforms,
            column_thresholds=col_thresholds,
            table_thresholds=list(t.get("table_thresholds") or []),
            select_columns=list(t.get("select_columns") or []),
            drop_columns=list(t.get("drop_columns") or []),
            jdbc_reader_options=dict(t.get("jdbc_reader_options") or {}),
        )
    return out


# --------------------------------------------------------------------------- #
# transpiled SQL (converted Databricks code)
# --------------------------------------------------------------------------- #
def _func_names(node) -> list[str]:
    names = set()
    for f in node.find_all(exp.Func):
        try:
            names.add(f.sql_name().upper())
        except Exception:
            names.add(type(f).__name__.upper())
    if list(node.find_all(exp.Case)):
        names.add("CASE")
    return sorted(n for n in names if n)


def _is_star_only(select) -> bool:
    """True if a SELECT projects only ``*`` (so real derivations live one level down)."""
    exprs = getattr(select, "expressions", None) or []
    if not exprs:
        return False
    return all(isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
               for e in exprs)


def _unwrap_select(select):
    """Descend to the projection-bearing SELECT.

    Handles the common migrated shapes where the per-column derivations sit one level
    down: ``SELECT * FROM (SELECT <cols> ...)`` and ``... (SELECT <cols> ... UNION ALL
    ...)`` (e.g. a duplicated-batch fan-out). Returns the innermost SELECT that actually
    lists columns, so its transforms are extracted rather than a bare ``*``."""
    seen: set[int] = set()
    while isinstance(select, exp.Select) and _is_star_only(select) and id(select) not in seen:
        seen.add(id(select))
        frm = select.args.get("from") or select.find(exp.From)
        sub = frm.find(exp.Subquery) if frm is not None else None
        inner = sub.this if sub is not None else None
        if isinstance(inner, exp.Union):
            inner = inner.this if isinstance(inner.this, exp.Select) else inner.find(exp.Select)
        if isinstance(inner, exp.Select):
            select = inner
            continue
        break
    return select


def _select_of(stmt):
    e = stmt.expression if hasattr(stmt, "expression") else None
    if isinstance(e, exp.Union):
        sel = e.this if isinstance(e.this, exp.Select) else e.find(exp.Select)
        return _unwrap_select(sel) if sel is not None else sel
    if isinstance(e, exp.Select):
        return _unwrap_select(e)
    sel = stmt.find(exp.Select)
    return _unwrap_select(sel) if sel is not None else sel


def parse_transpiled_sql(sql_text: str, read: str = "databricks") -> dict[str, TableMapping]:
    """Parse converted SQL into per-target-table column transforms (best effort)."""

    if not _HAS_SQLGLOT or not sql_text.strip():
        return {}
    out: dict[str, TableMapping] = {}
    try:
        statements = sqlglot.parse(sql_text, read=read)
    except Exception:
        return {}
    for stmt in statements:
        if stmt is None:
            continue
        try:
            if not isinstance(stmt, (exp.Insert, exp.Create)):
                continue
            tgt_tbl = stmt.this.find(exp.Table) if not isinstance(stmt.this, exp.Table) else stmt.this
            select = _select_of(stmt)
            if tgt_tbl is None or select is None:
                continue
            tgt_key = _short(tgt_tbl.name)
            mapping = out.setdefault(tgt_key, TableMapping(target_table=tgt_tbl.sql()))

            frm = select.args.get("from") or select.find(exp.From)
            if frm is not None:
                src = frm.find(exp.Table)
                if src is not None:
                    mapping.source_table = src.sql()
                # capture FROM + JOINs so a reconstruction can resolve joined lookup tables
                if not mapping.from_sql:
                    parts = [frm.sql(dialect=read)]
                    parts += [j.sql(dialect=read) for j in (select.args.get("joins") or [])]
                    mapping.from_sql = " ".join(parts)
            where = select.args.get("where")
            if where is not None and not mapping.target_filter:
                mapping.target_filter = where.this.sql(dialect=read)

            for proj in select.expressions:
                col = proj.alias_or_name
                if not col:
                    continue
                underlying = proj.this if isinstance(proj, exp.Alias) else proj
                mapping.transforms[col] = ColumnTransform(
                    target_column=col,
                    expr=underlying.sql(dialect=read),
                    functions=_func_names(underlying),
                    is_direct=isinstance(underlying, exp.Column),
                )
        except Exception:
            continue
    return out


# --------------------------------------------------------------------------- #
# source scripts (original-dialect DDL) -> declared column types
# --------------------------------------------------------------------------- #
def parse_source_ddl(sql_text: str, read: str = "snowflake") -> dict[str, dict[str, str]]:
    """Extract per-table declared column types from source DDL (CREATE TABLE).

    Returns {short_table_name: {column_lower: declared_type}}. Used to confirm
    type/precision and timezone findings from the *source* schema (e.g. a source
    NUMBER(18,4) migrated to DECIMAL(18,2) is a real scale loss).
    """

    if not _HAS_SQLGLOT or not sql_text.strip():
        return {}
    out: dict[str, dict[str, str]] = {}
    try:
        statements = sqlglot.parse(sql_text, read=read)
    except Exception:
        return {}
    for stmt in statements:
        if not isinstance(stmt, exp.Create):
            continue
        tbl = stmt.find(exp.Table)
        schema = stmt.this if isinstance(stmt.this, exp.Schema) else None
        if tbl is None or schema is None:
            continue
        cols: dict[str, str] = {}
        for cdef in schema.find_all(exp.ColumnDef):
            try:
                cols[cdef.name.lower()] = cdef.args["kind"].sql(dialect=read).upper()
            except Exception:
                continue
        if cols:
            out[_short(tbl.name)] = cols
    return out


def parse_source_dir(path: str | Path, read: str = "snowflake") -> dict[str, dict[str, str]]:
    p = Path(path)
    files = [p] if p.is_file() else list(p.rglob("*.sql")) if p.exists() else []
    merged: dict[str, dict[str, str]] = {}
    for f in files:
        try:
            for k, cols in parse_source_ddl(f.read_text(), read=read).items():
                merged.setdefault(k, {}).update(cols)
        except Exception:
            continue
    return merged


def parse_transpiled_dir(path: str | Path) -> dict[str, TableMapping]:
    p = Path(path)
    files = [p] if p.is_file() else list(p.rglob("*.sql")) if p.exists() else []
    merged: dict[str, TableMapping] = {}
    for f in files:
        try:
            for k, m in parse_transpiled_sql(f.read_text()).items():
                for ct in m.transforms.values():   # tag each derivation with its source file
                    ct.source_file = ct.source_file or f.name
                if k not in merged:
                    merged[k] = m
                else:
                    merged[k].transforms.update(m.transforms)
                    merged[k].source_table = merged[k].source_table or m.source_table
                    merged[k].target_filter = merged[k].target_filter or m.target_filter
                    merged[k].from_sql = merged[k].from_sql or m.from_sql
        except Exception:
            continue
    return merged


# --------------------------------------------------------------------------- #
# transpile error report (Lakebridge --error-file-path)
# --------------------------------------------------------------------------- #
_ERR_RE = re.compile(
    r"code=(?P<code>[^,]*),\s*kind=(?P<kind>\w+),\s*severity=(?P<sev>\w+),\s*"
    r"path='(?P<path>[^']*)',\s*message='(?P<msg>.*)'\)?$"
)


def parse_transpile_errors(path: str | Path) -> list[TranspileIssue]:
    p = Path(path)
    if not p.exists():
        return []
    issues: list[TranspileIssue] = []
    for line in p.read_text().splitlines():
        m = _ERR_RE.search(line)
        if m:
            issues.append(
                TranspileIssue(path=m.group("path"), kind=m.group("kind"),
                               severity=m.group("sev"), message=m.group("msg"))
            )
    return issues


# --------------------------------------------------------------------------- #
# unified builder
# --------------------------------------------------------------------------- #
def _types_from_source_file(path: str | Path, table: str, read: str) -> dict[str, str]:
    d = parse_source_dir(path, read=read)
    if _short(table) in d:
        return d[_short(table)]
    return next(iter(d.values())) if len(d) == 1 else {}


def _mapping_from_target_file(path: str | Path, table: str) -> Optional[TableMapping]:
    d = parse_transpiled_dir(path)
    if _short(table) in d:
        return d[_short(table)]
    return next(iter(d.values())) if len(d) == 1 else None


def apply_table_manifest(
    mapping: dict[str, TableMapping],
    manifest: list[dict],
    source_dialect: str = "snowflake",
) -> dict[str, TableMapping]:
    """Overlay an explicit per-table manifest onto ``mapping``.

    Each entry ties one target table to its own source/target script (and optional
    key/date/filter overrides), removing any file->table ambiguity of folder scans::

        tables:
          - target: fact_orders
            source: fact_orders            # optional; defaults to target
            source_script: .../fact_orders_source.sql
            target_script: .../fact_orders_target.sql
            join_keys: [order_id]          # optional override
            date_column: order_ts          # optional override
    """

    for entry in manifest or []:
        tgt = entry.get("target") or entry.get("target_name")
        if not tgt:
            continue
        k = _short(tgt)
        m = mapping.setdefault(k, TableMapping(target_table=tgt))
        m.target_table = m.target_table or tgt
        if entry.get("source") or entry.get("source_name"):
            m.source_table = entry.get("source") or entry.get("source_name")
        m.source_table = m.source_table or tgt
        if entry.get("join_keys"):
            m.join_keys = list(entry["join_keys"])
        if entry.get("date_column"):
            m.date_column = entry["date_column"]
        if entry.get("target_filter"):
            m.target_filter = entry["target_filter"]
        if entry.get("target_script"):
            tm2 = _mapping_from_target_file(entry["target_script"], tgt)
            if tm2 is not None:
                m.transforms.update(tm2.transforms)
                m.source_table = m.source_table or tm2.source_table
                m.target_filter = m.target_filter or tm2.target_filter
        if entry.get("source_script"):
            types = _types_from_source_file(entry["source_script"], m.source_table or tgt, source_dialect)
            if types:
                m.source_types = types
    return mapping


def build_mapping(
    recon_config_path: str | Path | None = None,
    transpiled_output: str | Path | None = None,
    transpile_error_file: str | Path | None = None,
    source_scripts: str | Path | None = None,
    source_dialect: str = "snowflake",
    table_manifest: list[dict] | None = None,
) -> dict[str, TableMapping]:
    """Merge recon config + source DDL + transpiled SQL + transpile errors into
    per-table mappings, keyed by the short (unqualified) target table name.

    ``source_scripts`` = original-dialect DDL (declared source types).
    ``transpiled_output`` = the deployed/transpiled target scripts.
    ``recon_config_path`` = the source<->target mapping (keys, columns, filters).
    ``table_manifest`` = explicit per-table source/target script paths (overrides the
    folder scans; use when file<->table names are ambiguous). All optional; each
    artifact simply adds more confirmation.
    """

    mapping: dict[str, TableMapping] = {}
    if recon_config_path:
        mapping.update(load_recon_config(recon_config_path))
    if transpiled_output:
        for k, m in parse_transpiled_dir(transpiled_output).items():
            if k in mapping:
                mapping[k].transforms.update(m.transforms)
                mapping[k].source_table = mapping[k].source_table or m.source_table
                mapping[k].target_filter = mapping[k].target_filter or m.target_filter
            else:
                mapping[k] = m
    if source_scripts:
        src_types = parse_source_dir(source_scripts, read=source_dialect)
        for m in mapping.values():
            types = src_types.get(_short(m.source_table)) or src_types.get(_short(m.target_table))
            if types:
                m.source_types = types
        # tables present only in source scripts (not in recon config / transpiled) —
        # keep them keyed by their own short name so type info is still available.
        for k, types in src_types.items():
            mapping.setdefault(k, TableMapping(source_table=k, target_table=k)).source_types = (
                mapping[k].source_types or types
            )
    if table_manifest:
        apply_table_manifest(mapping, table_manifest, source_dialect=source_dialect)
    if transpile_error_file:
        issues = parse_transpile_errors(transpile_error_file)
        for m in mapping.values():
            tgt_short = _short(m.target_table)
            m.transpile_issues = [i for i in issues if tgt_short in i.path.lower()]
    return mapping
