"""Ingest Lakebridge reconcile output into normalized ``Finding`` objects.

Reads the reconcile ``main`` / ``metrics`` / ``details`` tables for one
``recon_id``. ``metrics`` is the source of truth for counts and which columns
mismatched; ``details`` supplies row-level samples used as evidence and probe
inputs.

Observed schema (Lakebridge / lakebridge reconcile):

- ``main``    : recon_table_id, recon_id, source_table<struct>, target_table<struct>, ...
- ``metrics`` : recon_metrics<struct{source_record_count, target_record_count,
                row_comparison{missing_in_source, missing_in_target},
                column_comparison{absolute_mismatch, mismatch_columns},
                schema_comparison}>, ...
- ``details`` : recon_type ('mismatch'|'missing_in_source'|'missing_in_target'|'schema'),
                data<array<map<string,string>>>

``details.data`` maps:
- mismatch  : ``<col>_base`` (source), ``<col>_compare`` (target), ``<col>_match``
              plus the join keys as plain columns.
- missing_* : the full row as a flat map.
- schema    : {source_column, source_datatype, databricks_column, databricks_datatype, is_valid}.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import re

from rca_engine.models import Finding, MismatchSample, ReconType, TableSummary

_DATE_RE = re.compile(r"(date|dt|_ts|timestamp|time|day|month|year)", re.IGNORECASE)


def _guess_date_col(names: list[str]) -> str | None:
    for n in names:
        if n and _DATE_RE.search(n):
            return n
    return None


class QueryRunner(Protocol):
    def query(self, sql: str) -> list[dict[str, Any]]: ...


def _as_obj(value: Any) -> Any:
    """Coerce a struct/array cell to a Python object (JSON string or already-parsed)."""

    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _fqn(struct: Any) -> str:
    s = _as_obj(struct)
    if isinstance(s, dict):
        parts = [s.get("catalog"), s.get("schema"), s.get("table_name")]
        return ".".join(p for p in parts if p)
    return str(s)


def _rows(data: Any) -> list[dict[str, Any]]:
    data = _as_obj(data)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _keys_of(row: dict[str, Any]) -> dict[str, Any]:
    """Join-key columns in a mismatch map are the plain (non-_base/_compare/_match) entries."""

    return {
        k: v for k, v in row.items()
        if not (k.endswith("_base") or k.endswith("_compare") or k.endswith("_match"))
    }


def _mismatch_samples(data: Any, columns: list[str], limit: int = 200) -> dict[str, list[MismatchSample]]:
    out: dict[str, list[MismatchSample]] = {c: [] for c in columns}
    for row in _rows(data):
        keys = _keys_of(row)
        for col in columns:
            base, compare, match = f"{col}_base", f"{col}_compare", f"{col}_match"
            if base not in row and compare not in row:
                continue
            mismatched = (str(row.get(match)).lower() == "false") if match in row \
                else (row.get(base) != row.get(compare))
            if not mismatched:
                continue
            if len(out[col]) < limit:
                out[col].append(
                    MismatchSample(
                        keys=keys,
                        column=col,
                        source_value=row.get(base),
                        target_value=row.get(compare),
                    )
                )
    return out


def _row_samples(data: Any, limit: int = 200) -> list[MismatchSample]:
    samples: list[MismatchSample] = []
    for row in _rows(data):
        if len(samples) >= limit:
            break
        samples.append(MismatchSample(keys=row))
    return samples


def ingest_with_summaries(
    runner: QueryRunner,
    recon_id: str,
    recon_catalog: str,
    recon_schema: str,
) -> tuple[list[Finding], list[TableSummary]]:
    base = f"{recon_catalog}.{recon_schema}"

    main_rows = runner.query(
        f"SELECT recon_table_id, source_table, target_table "
        f"FROM {base}.main WHERE recon_id = '{recon_id}'"
    )

    findings: list[Finding] = []
    summaries: list[TableSummary] = []
    for m in main_rows:
        table_id = m.get("recon_table_id")
        source_table = _fqn(m.get("source_table"))
        target_table = _fqn(m.get("target_table"))

        metrics = runner.query(
            "SELECT recon_metrics.source_record_count AS source_record_count, "
            "recon_metrics.target_record_count AS target_record_count, "
            "recon_metrics.row_comparison.missing_in_source AS missing_in_source, "
            "recon_metrics.row_comparison.missing_in_target AS missing_in_target, "
            "recon_metrics.column_comparison.absolute_mismatch AS absolute_mismatch, "
            "recon_metrics.column_comparison.mismatch_columns AS mismatch_columns, "
            "recon_metrics.schema_comparison AS schema_comparison "
            f"FROM {base}.metrics WHERE recon_table_id = {table_id}"
        )
        mx = metrics[0] if metrics else {}

        def _int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        def _bool(v: Any) -> bool:
            return str(v).lower() == "true"

        source_count = _int(mx.get("source_record_count"))
        target_count = _int(mx.get("target_record_count"))
        missing_in_source = _int(mx.get("missing_in_source"))
        missing_in_target = _int(mx.get("missing_in_target"))
        mismatch_columns = [c.strip() for c in str(mx.get("mismatch_columns") or "").split(",") if c.strip()]
        schema_ok = _bool(mx.get("schema_comparison")) if mx.get("schema_comparison") is not None else True

        detail_rows = runner.query(
            f"SELECT recon_type, data FROM {base}.details WHERE recon_table_id = {table_id}"
        )
        by_type: dict[str, Any] = {}
        for d in detail_rows:
            by_type.setdefault(str(d.get("recon_type")), []).extend(_rows(d.get("data")))

        common = dict(recon_id=recon_id, source_table=source_table, target_table=target_table)

        # Column mismatches (one finding per mismatched column).
        if mismatch_columns:
            per_col = _mismatch_samples(by_type.get("mismatch"), mismatch_columns)
            for col in mismatch_columns:
                findings.append(
                    Finding(
                        **common,
                        recon_type=ReconType.COLUMN_MISMATCH,
                        column=col,
                        mismatch_count=len(per_col.get(col, [])),
                        total_count=source_count,
                        samples=per_col.get(col, []),
                        metadata={"absolute_mismatch": _int(mx.get("absolute_mismatch"))},
                    )
                )

        # Missing rows.
        if missing_in_target:
            findings.append(
                Finding(
                    **common,
                    recon_type=ReconType.MISSING_IN_TARGET,
                    mismatch_count=missing_in_target,
                    total_count=source_count,
                    samples=_row_samples(by_type.get("missing_in_target")),
                )
            )
        if missing_in_source:
            findings.append(
                Finding(
                    **common,
                    recon_type=ReconType.MISSING_IN_SOURCE,
                    mismatch_count=missing_in_source,
                    total_count=target_count,
                    samples=_row_samples(by_type.get("missing_in_source")),
                )
            )

        # Schema / datatype differences.
        if not schema_ok:
            invalid = [r for r in _rows(by_type.get("schema")) if str(r.get("is_valid")).lower() == "false"]
            findings.append(
                Finding(
                    **common,
                    recon_type=ReconType.SCHEMA,
                    mismatch_count=len(invalid),
                    samples=[MismatchSample(keys=r) for r in invalid],
                    metadata={"schema_diffs": invalid},
                )
            )

        # Per-table summary (captured for every pair, clean or not).
        mismatch_rows = _rows(by_type.get("mismatch"))
        join_keys = list(_keys_of(mismatch_rows[0]).keys()) if mismatch_rows else []
        candidate_names = list(mismatch_columns) + join_keys
        for r in _rows(by_type.get("missing_in_target")) + _rows(by_type.get("missing_in_source")):
            candidate_names += list(r.keys())
        summaries.append(
            TableSummary(
                source_table=source_table,
                target_table=target_table,
                source_count=source_count,
                target_count=target_count,
                missing_in_source=missing_in_source,
                missing_in_target=missing_in_target,
                absolute_mismatch=_int(mx.get("absolute_mismatch")),
                mismatch_columns=mismatch_columns,
                schema_ok=schema_ok,
                join_keys=join_keys,
                date_column=_guess_date_col(candidate_names),
            )
        )

    return findings, summaries


def ingest(
    runner: QueryRunner,
    recon_id: str,
    recon_catalog: str,
    recon_schema: str,
    key_columns: list[str] | None = None,  # unused; kept for API compatibility
) -> list[Finding]:
    findings, _ = ingest_with_summaries(runner, recon_id, recon_catalog, recon_schema)
    return findings
