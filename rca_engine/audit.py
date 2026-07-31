"""Append-only audit trail for the ReconResolve pipeline.

Every orchestration step — a triggered reconcile, an RCA run, notebook publishing —
appends one row to a single Delta table so there is a durable record of *what ran,
when, by whom, on what, and the outcome*. Rows from one orchestration share a
``run_id`` (reconcile + rca group together).

Everything here is **best-effort**: if the table can't be created or written (e.g.
missing privileges), we log and return — auditing must never break the main flow.
The writer only needs a ``QueryRunner`` (``.query(sql)``), so the app (service
principal), the skill (notebook user), and the CLI all share it.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from rca_engine.ingest import QueryRunner

# Ordered (column, type). Flat + JSON-as-string so any warehouse can write it.
_COLUMNS: list[tuple[str, str]] = [
    ("audit_id", "STRING"),
    ("run_id", "STRING"),
    ("operation", "STRING"),      # reconcile | rca | reconcile+rca | analyze_table
    ("status", "STRING"),         # ok | error
    ("tool", "STRING"),           # app | skill | cli
    ("run_by", "STRING"),
    ("catalog", "STRING"),
    ("source_schema", "STRING"),
    ("target_schema", "STRING"),
    ("recon_id", "STRING"),
    ("tables", "STRING"),         # JSON (pair specs / results)
    ("table_pairs", "BIGINT"),
    ("pairs_ok", "BIGINT"),
    ("pairs_error", "BIGINT"),
    ("tables_with_diffs", "BIGINT"),
    ("findings_total", "BIGINT"),
    ("notebook_path", "STRING"),
    ("message", "STRING"),
    ("duration_ms", "BIGINT"),
    ("started_ts", "TIMESTAMP"),
    ("ended_ts", "TIMESTAMP"),
    ("inserted_ts", "TIMESTAMP"),
]


def _lit(v: Any) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def _ts_lit(epoch: float | None) -> str:
    if not epoch:
        return "current_timestamp()"
    iso = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return f"to_timestamp('{iso}')"


def ensure_audit_table(runner: QueryRunner, audit_table: str) -> bool:
    """CREATE TABLE IF NOT EXISTS the audit table. Returns False on failure."""
    if not audit_table:
        return False
    cols = ", ".join(f"{c} {t}" for c, t in _COLUMNS)
    try:
        runner.query(f"CREATE TABLE IF NOT EXISTS {audit_table} ({cols}) USING DELTA")
        return True
    except Exception as exc:  # pragma: no cover - perms/env dependent
        print(f"[audit] could not ensure {audit_table}: {exc}")
        return False


def log_audit(
    runner: QueryRunner,
    audit_table: str,
    *,
    operation: str,
    status: str,
    tool: str = "app",
    run_id: str | None = None,
    run_by: str | None = None,
    catalog: str | None = None,
    source_schema: str | None = None,
    target_schema: str | None = None,
    recon_id: str | None = None,
    tables: Any = None,
    table_pairs: int = 0,
    pairs_ok: int = 0,
    pairs_error: int = 0,
    tables_with_diffs: int = 0,
    findings_total: int = 0,
    notebook_path: str | None = None,
    message: str = "",
    started_ts: float | None = None,
    ensure: bool = True,
) -> str:
    """Append one audit row. Returns the ``run_id`` (generated if not supplied).
    Best-effort: swallows all errors so auditing never breaks the pipeline."""
    run_id = run_id or uuid.uuid4().hex
    if not audit_table:
        return run_id
    try:
        if ensure:
            ensure_audit_table(runner, audit_table)
        now = datetime.now(tz=timezone.utc).timestamp()
        dur = int((now - started_ts) * 1000) if started_ts else 0
        tables_json = None
        if tables is not None:
            try:
                tables_json = json.dumps(tables, default=str)[:60000]
            except Exception:
                tables_json = None
        vals = [
            _lit(uuid.uuid4().hex), _lit(run_id), _lit(operation), _lit(status), _lit(tool),
            _lit(run_by), _lit(catalog), _lit(source_schema), _lit(target_schema), _lit(recon_id),
            _lit(tables_json), str(int(table_pairs)), str(int(pairs_ok)), str(int(pairs_error)),
            str(int(tables_with_diffs)), str(int(findings_total)), _lit(notebook_path),
            _lit(message[:4000] if message else message), str(int(dur)),
            _ts_lit(started_ts), "current_timestamp()", "current_timestamp()",
        ]
        cols = ", ".join(c for c, _ in _COLUMNS)
        runner.query(f"INSERT INTO {audit_table} ({cols}) VALUES ({', '.join(vals)})")
    except Exception as exc:  # pragma: no cover - perms/env dependent
        print(f"[audit] write failed for {audit_table}: {exc}")
    return run_id


def read_audit(runner: QueryRunner, audit_table: str, limit: int = 50) -> list[dict[str, Any]]:
    """Recent audit rows, newest first. Empty list if unavailable."""
    if not audit_table:
        return []
    try:
        return runner.query(
            "SELECT run_id, recon_id, operation, status, tool, run_by, catalog, "
            "source_schema, target_schema, table_pairs, pairs_ok, pairs_error, "
            "tables_with_diffs, findings_total, notebook_path, message, duration_ms, "
            "started_ts, ended_ts "
            f"FROM {audit_table} ORDER BY inserted_ts DESC LIMIT {int(limit)}"
        )
    except Exception:
        return []
