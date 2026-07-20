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
    transpile_issues: list[TranspileIssue] = field(default_factory=list)

    def transform_for(self, target_col: str) -> Optional[ColumnTransform]:
        return self.transforms.get(target_col)

    def source_type_of(self, col: str) -> Optional[str]:
        return self.source_types.get(col.lower()) if col else None


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
        out[_short(tgt)] = TableMapping(
            source_table=src,
            target_table=tgt,
            join_keys=keys,
            date_column=_DATE_RE.search(" ".join(keys)) and next((k for k in keys if _DATE_RE.search(k)), None),
            column_map=col_map,
            source_filter=(filters.get("source") or ""),
            target_filter=(filters.get("target") or ""),
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


def _select_of(stmt):
    e = stmt.expression if hasattr(stmt, "expression") else None
    if isinstance(e, exp.Union):
        return e.this if isinstance(e.this, exp.Select) else e.find(exp.Select)
    if isinstance(e, exp.Select):
        return e
    return stmt.find(exp.Select)


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

            frm = select.args.get("from")
            if frm is not None:
                src = frm.find(exp.Table)
                if src is not None:
                    mapping.source_table = src.sql()
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
                if k not in merged:
                    merged[k] = m
                else:
                    merged[k].transforms.update(m.transforms)
                    merged[k].source_table = merged[k].source_table or m.source_table
                    merged[k].target_filter = merged[k].target_filter or m.target_filter
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
def build_mapping(
    recon_config_path: str | Path | None = None,
    transpiled_output: str | Path | None = None,
    transpile_error_file: str | Path | None = None,
    source_scripts: str | Path | None = None,
    source_dialect: str = "snowflake",
) -> dict[str, TableMapping]:
    """Merge recon config + source DDL + transpiled SQL + transpile errors into
    per-table mappings, keyed by the short (unqualified) target table name.

    ``source_scripts`` = original-dialect DDL (declared source types).
    ``transpiled_output`` = the deployed/transpiled target scripts.
    ``recon_config_path`` = the source<->target mapping (keys, columns, filters).
    All optional; each artifact simply adds more confirmation.
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
    if transpile_error_file:
        issues = parse_transpile_errors(transpile_error_file)
        for m in mapping.values():
            tgt_short = _short(m.target_table)
            m.transpile_issues = [i for i in issues if tgt_short in i.path.lower()]
    return mapping
