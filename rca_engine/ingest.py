"""Ingest Lakebridge reconcile output into normalized ``Finding`` objects.

Lakebridge writes reconcile results to a metastore schema (default ``remorph``)
with ``main`` / ``metrics`` / ``details`` tables. Exact column names vary by
version, so ingestion goes through a small ``QueryRunner`` and defensive parsing.
The concrete SQL is finalized in Phase 2 once we observe the real output schema.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from rca_engine.models import Finding, MismatchSample, ReconType


class QueryRunner(Protocol):
    """Minimal execution backend: run SQL, return rows as dicts.

    Implementations: Databricks SQL connector, a Spark session wrapper, or a
    fake for tests.
    """

    def query(self, sql: str) -> list[dict[str, Any]]: ...


_RECON_TYPE_MAP = {
    "mismatch": ReconType.COLUMN_MISMATCH,
    "missing_in_target": ReconType.MISSING_IN_TARGET,
    "missing_in_source": ReconType.MISSING_IN_SOURCE,
    "schema": ReconType.SCHEMA,
}


def _coerce_samples(raw: Any, key_columns: list[str]) -> list[MismatchSample]:
    """Turn a details ``data`` payload into MismatchSample rows.

    Lakebridge stores mismatch samples as rows with ``<col>_base``/``<col>_compare``
    pairs (or a JSON array of maps). We pair those up per column.
    """

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    samples: list[MismatchSample] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        keys = {k: row[k] for k in key_columns if k in row}
        # Detect base/compare column pairs.
        bases = {k[:-5] for k in row if k.endswith("_base")}
        compares = {k[:-8] for k in row if k.endswith("_compare")}
        for col in sorted(bases & compares):
            samples.append(
                MismatchSample(
                    keys=keys,
                    column=col,
                    source_value=row.get(f"{col}_base"),
                    target_value=row.get(f"{col}_compare"),
                )
            )
        if not (bases & compares):
            samples.append(MismatchSample(keys=keys))
    return samples


def ingest(
    runner: QueryRunner,
    recon_id: str,
    recon_catalog: str,
    recon_schema: str,
    key_columns: list[str] | None = None,
) -> list[Finding]:
    """Load all findings for a recon run.

    Note: table/column names below match the common Lakebridge layout and are
    verified against the live schema in Phase 2.
    """

    key_columns = key_columns or []
    base = f"{recon_catalog}.{recon_schema}"

    main_rows = runner.query(
        f"SELECT recon_table_id, source_table, target_table "
        f"FROM {base}.main WHERE recon_id = '{recon_id}'"
    )

    findings: list[Finding] = []
    for m in main_rows:
        table_id = m.get("recon_table_id")
        detail_rows = runner.query(
            f"SELECT recon_type, data FROM {base}.details "
            f"WHERE recon_table_id = '{table_id}'"
        )
        for d in detail_rows:
            recon_type = _RECON_TYPE_MAP.get(str(d.get("recon_type")), ReconType.COLUMN_MISMATCH)
            samples = _coerce_samples(d.get("data"), key_columns)
            # Column-level findings are split per column for precise classification.
            if recon_type == ReconType.COLUMN_MISMATCH:
                by_col: dict[str | None, list[MismatchSample]] = {}
                for s in samples:
                    by_col.setdefault(s.column, []).append(s)
                for col, col_samples in by_col.items():
                    findings.append(
                        Finding(
                            recon_id=recon_id,
                            source_table=str(m.get("source_table")),
                            target_table=str(m.get("target_table")),
                            recon_type=recon_type,
                            column=col,
                            mismatch_count=len(col_samples),
                            samples=col_samples,
                        )
                    )
            else:
                findings.append(
                    Finding(
                        recon_id=recon_id,
                        source_table=str(m.get("source_table")),
                        target_table=str(m.get("target_table")),
                        recon_type=recon_type,
                        mismatch_count=len(samples),
                        samples=samples,
                    )
                )
    return findings
