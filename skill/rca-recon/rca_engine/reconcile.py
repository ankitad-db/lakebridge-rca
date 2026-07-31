"""App-native reconcile: compare a source table to its migrated target on the SQL
warehouse and write Lakebridge-compatible ``main``/``metrics``/``details`` rows under
a fresh ``recon_id``.

This lets the ReconResolve app *trigger* a reconciliation itself (no Lakebridge CLI /
Spark job needed) whenever both sides are query-able from the warehouse — the retail
test bed keeps the simulated Snowflake source (``mig_source_sim``) and the migrated
target (``mig_target``) in the same catalog, so a warehouse can join them directly.

The output schema is exactly what ``ingest``/``discovery`` already read, so the
resulting ``recon_id`` flows into the *same* RCA engine the Genie skill runs — the
app just picks it up like any other reconcile run.

Design notes / guardrails:
* **Join keys** are taken from the caller, else auto-detected (id-like columns that are
  unique + non-null on the source), capped at ``max_key_tries`` attempts.
* **Renamed columns** are handled via ``column_mapping`` so ``report_type=all`` does not
  abort (the failure mode of Lakebridge's own comparison); unmapped one-sided columns
  are reported as schema diffs instead of aborting the run.
* Each pair is isolated: a missing table / undetectable key / query error marks that
  pair ``error`` and the run continues, so one bad pair never sinks the whole recon.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from rca_engine.ingest import QueryRunner

# Columns that are comparison metadata, never join keys / values.
_NULL = "_null_recon_"
_DATE_RE = re.compile(r"(date|dt|day|week|month|year|_ts|timestamp|time)", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Specs / results
# --------------------------------------------------------------------------- #
@dataclass
class TablePairSpec:
    source_table: str                                   # short name (within source schema)
    target_table: str = ""                              # defaults to source_table
    join_keys: list[str] = field(default_factory=list)  # optional; auto-detected if empty
    column_mapping: dict[str, str] = field(default_factory=dict)  # source_col -> target_col

    def __post_init__(self) -> None:
        self.target_table = self.target_table or self.source_table


@dataclass
class PairResult:
    source_table: str
    target_table: str
    status: str = "ok"                 # ok | error
    message: str = ""
    join_keys: list[str] = field(default_factory=list)
    keys_origin: str = ""              # provided | auto-detected
    source_count: int = 0
    target_count: int = 0
    missing_in_target: int = 0
    missing_in_source: int = 0
    absolute_mismatch: int = 0
    mismatch_columns: list[str] = field(default_factory=list)
    schema_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_table": self.source_table,
            "target_table": self.target_table,
            "status": self.status,
            "message": self.message,
            "join_keys": self.join_keys,
            "keys_origin": self.keys_origin,
            "source_count": self.source_count,
            "target_count": self.target_count,
            "missing_in_target": self.missing_in_target,
            "missing_in_source": self.missing_in_source,
            "absolute_mismatch": self.absolute_mismatch,
            "mismatch_columns": self.mismatch_columns,
            "schema_ok": self.schema_ok,
        }


@dataclass
class ReconRunResult:
    recon_id: str
    catalog: str
    source_schema: str
    target_schema: str
    pairs: list[PairResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recon_id": self.recon_id,
            "catalog": self.catalog,
            "source_schema": self.source_schema,
            "target_schema": self.target_schema,
            "pairs": [p.to_dict() for p in self.pairs],
            "pairs_ok": sum(1 for p in self.pairs if p.status == "ok"),
            "pairs_error": sum(1 for p in self.pairs if p.status == "error"),
        }


# --------------------------------------------------------------------------- #
# SQL helpers
# --------------------------------------------------------------------------- #
def _bt(name: str) -> str:
    """Backtick-quote an identifier part."""
    return "`" + str(name).replace("`", "``") + "`"


def _fq(catalog: str, schema: str, table: str) -> str:
    return f"{_bt(catalog)}.{_bt(schema)}.{_bt(table)}"


def _sql_str(v: Any) -> str:
    """A SQL string literal (or NULL) for a Python value."""
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def _map_literal(pairs: list[tuple[str, Any]]) -> str:
    parts: list[str] = []
    for k, v in pairs:
        parts.append(_sql_str(k))
        parts.append(_sql_str(v))
    return "map(" + ", ".join(parts) + ")" if parts else "map()"


def _array_of_maps(rows: list[list[tuple[str, Any]]]) -> str:
    if not rows:
        return "array()"
    return "array(" + ", ".join(_map_literal(r) for r in rows) + ")"


def _one(runner: QueryRunner, sql: str) -> dict[str, Any]:
    rows = runner.query(sql)
    return rows[0] if rows else {}


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Schema / key discovery
# --------------------------------------------------------------------------- #
def table_columns(runner: QueryRunner, catalog: str, schema: str, table: str) -> dict[str, str]:
    """Ordered {column_lower: data_type} for a table, via information_schema.
    Empty dict if the table does not exist."""
    rows = runner.query(
        "SELECT column_name, data_type, ordinal_position "
        f"FROM {_bt(catalog)}.information_schema.columns "
        f"WHERE table_schema = {_sql_str(schema)} AND table_name = {_sql_str(table)} "
        "ORDER BY ordinal_position"
    )
    return {str(r.get("column_name")).lower(): str(r.get("data_type") or "") for r in rows}


def _key_candidates(table: str, columns: list[str]) -> list[list[str]]:
    """Ordered candidate key-sets to try, most-likely first: single id-like columns,
    the set of all id-like columns, then id-like columns paired with a date/time
    column (covers grain keys like ``(store_id, sales_date)``)."""
    cols = list(columns)
    short = table.split(".")[-1].strip("`").lower()
    singles: list[str] = []
    if "id" in cols:
        singles.append("id")
    if f"{short}_id" in cols:
        singles.append(f"{short}_id")
    singles += [c for c in cols if c.endswith("_id") and c not in singles]
    id_like = [c for c in cols if c == "id" or c.endswith("_id")]
    date_like = [c for c in cols if _DATE_RE.search(c) and c not in id_like]

    candidates: list[list[str]] = [[c] for c in singles]
    if len(id_like) > 1:
        candidates.append(id_like)                       # all id-like together
    for d in date_like[:2]:                              # grain key: id-like + a date column
        if id_like:
            candidates.append(id_like + [d])
        else:
            candidates.append([d])
    # De-dup while preserving order.
    seen, uniq = set(), []
    for cand in candidates:
        key = tuple(cand)
        if key not in seen:
            seen.add(key)
            uniq.append(cand)
    return uniq


def _is_unique_key(runner: QueryRunner, fq_table: str, keys: list[str]) -> bool:
    key_cols = ", ".join(_bt(k) for k in keys)
    not_null = " AND ".join(f"{_bt(k)} IS NOT NULL" for k in keys)
    row = _one(
        runner,
        f"SELECT count(*) AS n, count(DISTINCT {key_cols}) AS d, "
        f"count_if(NOT ({not_null})) AS nulls FROM {fq_table}"
    )
    n, d, nulls = _int(row.get("n")), _int(row.get("d")), _int(row.get("nulls"))
    return n > 0 and n == d and nulls == 0


def detect_join_keys(
    runner: QueryRunner,
    catalog: str,
    schema: str,
    table: str,
    columns: list[str],
    max_key_tries: int = 8,
) -> tuple[list[str], str]:
    """Best-effort unique join key. Returns (keys, note). ``keys`` empty if none of
    the first ``max_key_tries`` candidates are unique + non-null on the source."""
    fq = _fq(catalog, schema, table)
    tried = 0
    for cand in _key_candidates(table, columns):
        if tried >= max_key_tries:
            break
        tried += 1
        try:
            if _is_unique_key(runner, fq, cand):
                return cand, f"auto-detected after {tried} attempt(s)"
        except Exception:
            continue
    return [], f"no unique key found in {tried} attempt(s); provide join_keys"


# --------------------------------------------------------------------------- #
# Per-pair reconcile
# --------------------------------------------------------------------------- #
def _base_type(dt: str) -> str:
    return (dt or "").split("(")[0].strip().upper()


def reconcile_pair(
    runner: QueryRunner,
    catalog: str,
    source_schema: str,
    target_schema: str,
    spec: TablePairSpec,
    sample_limit: int = 100,
    max_key_tries: int = 6,
) -> tuple[PairResult, dict[str, list[list[tuple[str, Any]]]]]:
    """Compare one pair. Returns (PairResult, details) where details maps
    recon_type -> list of rows (each row a list of (key, value) tuples)."""
    res = PairResult(source_table=spec.source_table, target_table=spec.target_table)
    details: dict[str, list[list[tuple[str, Any]]]] = {}

    src_cols = table_columns(runner, catalog, source_schema, spec.source_table)
    tgt_cols = table_columns(runner, catalog, target_schema, spec.target_table)
    if not src_cols:
        res.status, res.message = "error", f"source table {source_schema}.{spec.source_table} not found"
        return res, details
    if not tgt_cols:
        res.status, res.message = "error", f"target table {target_schema}.{spec.target_table} not found"
        return res, details

    src_fq = _fq(catalog, source_schema, spec.source_table)
    tgt_fq = _fq(catalog, target_schema, spec.target_table)
    colmap = {k.lower(): v.lower() for k, v in spec.column_mapping.items()}

    def tgt_of(src_col: str) -> str:
        return colmap.get(src_col, src_col)

    # ---- join keys -------------------------------------------------------- #
    if spec.join_keys:
        res.join_keys = [k.lower() for k in spec.join_keys]
        res.keys_origin = "provided"
    else:
        keys, note = detect_join_keys(runner, catalog, source_schema, spec.source_table,
                                      list(src_cols), max_key_tries=max_key_tries)
        res.join_keys, res.keys_origin = keys, note
    if not res.join_keys:
        res.status = "error"
        res.message = f"could not identify a join key ({res.keys_origin})"
        return res, details
    # Keys must exist on both sides (respecting mapping).
    missing_keys = [k for k in res.join_keys if k not in src_cols or tgt_of(k) not in tgt_cols]
    if missing_keys:
        res.status = "error"
        res.message = f"join key(s) {missing_keys} not present on both tables"
        return res, details

    # ---- comparable value columns ---------------------------------------- #
    keyset = set(res.join_keys)
    compare_cols = [c for c in src_cols if c not in keyset and tgt_of(c) in tgt_cols]

    def _on() -> str:
        return " AND ".join(f"s.{_bt(k)} <=> t.{_bt(tgt_of(k))}" for k in res.join_keys)

    # ---- counts ----------------------------------------------------------- #
    res.source_count = _int(_one(runner, f"SELECT count(*) AS n FROM {src_fq}").get("n"))
    res.target_count = _int(_one(runner, f"SELECT count(*) AS n FROM {tgt_fq}").get("n"))
    res.missing_in_target = _int(_one(
        runner, f"SELECT count(*) AS n FROM {src_fq} s LEFT ANTI JOIN {tgt_fq} t ON {_on()}"
    ).get("n"))
    res.missing_in_source = _int(_one(
        runner, f"SELECT count(*) AS n FROM {tgt_fq} t LEFT ANTI JOIN {src_fq} s ON {_on()}"
    ).get("n"))

    # ---- schema comparison (type diffs + one-sided/renamed columns) ------- #
    schema_rows: list[list[tuple[str, Any]]] = []
    for c in src_cols:
        if c in keyset:
            continue
        tc = tgt_of(c)
        if tc not in tgt_cols:
            schema_rows.append([("source_column", c), ("source_datatype", src_cols[c]),
                                ("databricks_column", _NULL), ("databricks_datatype", _NULL),
                                ("is_valid", "false")])
        elif _base_type(src_cols[c]) != _base_type(tgt_cols[tc]):
            schema_rows.append([("source_column", c), ("source_datatype", src_cols[c]),
                                ("databricks_column", tc), ("databricks_datatype", tgt_cols[tc]),
                                ("is_valid", "false")])
    res.schema_ok = not schema_rows
    if schema_rows:
        details["schema"] = schema_rows

    # ---- column mismatches (per-column counts + samples) ------------------ #
    if compare_cols:
        agg_parts = [
            f"count_if(NOT (s.{_bt(c)} <=> t.{_bt(tgt_of(c))})) AS c{i}"
            for i, c in enumerate(compare_cols)
        ]
        any_mismatch = " OR ".join(f"NOT (s.{_bt(c)} <=> t.{_bt(tgt_of(c))})" for c in compare_cols)
        agg = _one(
            runner,
            f"SELECT count(*) AS common, count_if({any_mismatch}) AS anym, "
            + ", ".join(agg_parts)
            + f" FROM {src_fq} s JOIN {tgt_fq} t ON {_on()}"
        )
        res.absolute_mismatch = _int(agg.get("anym"))
        res.mismatch_columns = [compare_cols[i] for i in range(len(compare_cols))
                                if _int(agg.get(f"c{i}")) > 0]

        if res.absolute_mismatch and res.mismatch_columns:
            sel = [f"s.{_bt(k)} AS {_bt(k)}" for k in res.join_keys]
            for c in res.mismatch_columns:
                sel.append(f"s.{_bt(c)} AS {_bt(c + '__b')}")
                sel.append(f"t.{_bt(tgt_of(c))} AS {_bt(c + '__c')}")
            sample_where = " OR ".join(
                f"NOT (s.{_bt(c)} <=> t.{_bt(tgt_of(c))})" for c in res.mismatch_columns
            )
            rows = runner.query(
                "SELECT " + ", ".join(sel)
                + f" FROM {src_fq} s JOIN {tgt_fq} t ON {_on()} WHERE {sample_where} "
                f"LIMIT {int(sample_limit)}"
            )
            mismatch_rows: list[list[tuple[str, Any]]] = []
            for r in rows:
                entry: list[tuple[str, Any]] = [(k, r.get(k)) for k in res.join_keys]
                for c in res.mismatch_columns:
                    b, cc = r.get(c + "__b"), r.get(c + "__c")
                    entry.append((f"{c}_base", b))
                    entry.append((f"{c}_compare", cc))
                    entry.append((f"{c}_match", "true" if str(b) == str(cc) else "false"))
                mismatch_rows.append(entry)
            details["mismatch"] = mismatch_rows

    # ---- missing-row samples --------------------------------------------- #
    if res.missing_in_target:
        details["missing_in_target"] = _missing_samples(
            runner, src_fq, tgt_fq, res.join_keys, tgt_of, list(src_cols), anti="target", limit=sample_limit
        )
    if res.missing_in_source:
        details["missing_in_source"] = _missing_samples(
            runner, src_fq, tgt_fq, res.join_keys, tgt_of, list(tgt_cols), anti="source", limit=sample_limit
        )
    return res, details


def _missing_samples(runner, src_fq, tgt_fq, keys, tgt_of, cols, anti, limit):
    on = " AND ".join(f"s.{_bt(k)} <=> t.{_bt(tgt_of(k))}" for k in keys)
    if anti == "target":  # rows in source, not in target
        sel = ", ".join(f"s.{_bt(c)} AS {_bt(c)}" for c in cols)
        sql = f"SELECT {sel} FROM {src_fq} s LEFT ANTI JOIN {tgt_fq} t ON {on} LIMIT {int(limit)}"
    else:                 # rows in target, not in source
        sel = ", ".join(f"t.{_bt(c)} AS {_bt(c)}" for c in cols)
        sql = f"SELECT {sel} FROM {tgt_fq} t LEFT ANTI JOIN {src_fq} s ON {on} LIMIT {int(limit)}"
    return [[(k, v) for k, v in r.items()] for r in runner.query(sql)]


# --------------------------------------------------------------------------- #
# Run + persist
# --------------------------------------------------------------------------- #
def _next_recon_table_id(runner: QueryRunner, base: str) -> int:
    try:
        row = _one(runner, f"SELECT max(recon_table_id) AS m FROM {base}.main")
        return _int(row.get("m")) + 1
    except Exception:
        return int(time.time() * 1000)


def _write_pair(runner, base, recon_id, table_id, catalog, source_schema, target_schema,
                spec, res, details) -> None:
    src_struct = (f"named_struct('catalog', {_sql_str(catalog)}, 'schema', {_sql_str(source_schema)}, "
                  f"'table_name', {_sql_str(spec.source_table)})")
    tgt_struct = (f"named_struct('catalog', {_sql_str(catalog)}, 'schema', {_sql_str(target_schema)}, "
                  f"'table_name', {_sql_str(spec.target_table)})")
    runner.query(
        f"INSERT INTO {base}.main (recon_table_id, recon_id, source_type, source_table, "
        "target_table, report_type, operation_name, start_ts, end_ts) VALUES "
        f"({table_id}, {_sql_str(recon_id)}, 'databricks', {src_struct}, {tgt_struct}, "
        "'all', 'reconcile', current_timestamp(), current_timestamp())"
    )
    cols_csv = ",".join(res.mismatch_columns)
    schema_cmp = "true" if res.schema_ok else "false"
    status = "true" if (res.missing_in_target == 0 and res.missing_in_source == 0
                        and res.absolute_mismatch == 0 and res.schema_ok) else "false"
    metrics = (
        "named_struct("
        f"'source_record_count', CAST({res.source_count} AS BIGINT), "
        f"'target_record_count', CAST({res.target_count} AS BIGINT), "
        f"'row_comparison', named_struct('missing_in_source', CAST({res.missing_in_source} AS BIGINT), "
        f"'missing_in_target', CAST({res.missing_in_target} AS BIGINT)), "
        f"'column_comparison', named_struct('absolute_mismatch', CAST({res.absolute_mismatch} AS BIGINT), "
        f"'threshold_mismatch', CAST(0 AS BIGINT), 'mismatch_columns', {_sql_str(cols_csv)}), "
        f"'schema_comparison', {schema_cmp})"
    )
    run_metrics = (f"named_struct('status', {status}, 'run_by_user', 'rca-genie-app', "
                   "'exception_message', '')")
    runner.query(
        f"INSERT INTO {base}.metrics (recon_table_id, recon_metrics, run_metrics, inserted_ts) "
        f"VALUES ({table_id}, {metrics}, {run_metrics}, current_timestamp())"
    )
    for recon_type, rows in details.items():
        if not rows:
            continue
        runner.query(
            f"INSERT INTO {base}.details (recon_table_id, recon_type, status, data, inserted_ts) "
            f"VALUES ({table_id}, {_sql_str(recon_type)}, false, {_array_of_maps(rows)}, current_timestamp())"
        )


def run_reconcile(
    runner: QueryRunner,
    catalog: str,
    source_schema: str,
    target_schema: str,
    specs: list[TablePairSpec],
    recon_schema: str = "reconcile",
    sample_limit: int = 100,
    max_key_tries: int = 6,
    progress: Any = None,
) -> ReconRunResult:
    """Reconcile each pair and persist Lakebridge-compatible rows under a new
    ``recon_id``. Per-pair failures are captured, not raised. ``progress`` is an
    optional callable ``(done, total, PairResult)`` for UI updates."""
    recon_id = uuid.uuid4().hex
    base = f"{_bt(catalog)}.{_bt(recon_schema)}"
    result = ReconRunResult(recon_id=recon_id, catalog=catalog,
                            source_schema=source_schema, target_schema=target_schema)
    table_id = _next_recon_table_id(runner, base)
    total = len(specs)
    for i, spec in enumerate(specs):
        try:
            res, details = reconcile_pair(runner, catalog, source_schema, target_schema, spec,
                                          sample_limit=sample_limit, max_key_tries=max_key_tries)
        except Exception as exc:  # never let one pair sink the run
            res = PairResult(source_table=spec.source_table, target_table=spec.target_table,
                             status="error", message=str(exc))
            details = {}
        if res.status == "ok":
            try:
                _write_pair(runner, base, recon_id, table_id, catalog, source_schema,
                            target_schema, spec, res, details)
                table_id += 1
            except Exception as exc:
                res.status, res.message = "error", f"write failed: {exc}"
        result.pairs.append(res)
        if callable(progress):
            try:
                progress(i + 1, total, res)
            except Exception:
                pass
    return result
