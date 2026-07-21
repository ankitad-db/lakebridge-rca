"""Discover Lakebridge reconcile runs so a user can pick a ``recon_id``.

The RCA needs a ``recon_id`` to analyze. Rather than requiring the user to hunt
for it, this lists the most recent runs from the reconcile ``main`` table (with a
lightweight join to ``metrics`` for a mismatch rollup) so they can choose.
"""

from __future__ import annotations

from typing import Any

from rca_engine.ingest import QueryRunner


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def list_recon_runs(
    runner: QueryRunner,
    recon_catalog: str,
    recon_schema: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent recon runs, newest first.

    Each entry: ``recon_id``, ``started``, ``ended``, ``table_pairs``,
    ``tables_with_diffs``, ``clean`` (bool). Defensive against a ``main`` table
    that lacks ``start_ts`` (falls back to no ordering).
    """

    base = f"{recon_catalog}.{recon_schema}"
    try:
        rows = runner.query(
            "SELECT recon_id, min(start_ts) AS started, max(end_ts) AS ended, "
            f"count(*) AS table_pairs FROM {base}.main "
            f"GROUP BY recon_id ORDER BY started DESC LIMIT {int(limit)}"
        )
    except Exception:
        # Older/edge schemas without start_ts — order by recon_id instead.
        rows = runner.query(
            "SELECT recon_id, count(*) AS table_pairs "
            f"FROM {base}.main GROUP BY recon_id ORDER BY recon_id DESC LIMIT {int(limit)}"
        )

    runs: list[dict[str, Any]] = []
    for r in rows:
        recon_id = r.get("recon_id")
        if not recon_id:
            continue
        with_diffs = _tables_with_diffs(runner, base, recon_id)
        pairs = _int(r.get("table_pairs"))
        runs.append({
            "recon_id": recon_id,
            "started": r.get("started"),
            "ended": r.get("ended"),
            "table_pairs": pairs,
            "tables_with_diffs": with_diffs,
            "clean": with_diffs == 0 and pairs > 0,
        })
    return runs


def _tables_with_diffs(runner: QueryRunner, base: str, recon_id: str) -> int:
    """Count table pairs in this run that have any row/column/schema difference."""
    try:
        rows = runner.query(
            "SELECT count(*) AS n FROM "
            f"(SELECT mt.recon_table_id FROM {base}.metrics mt "
            f"JOIN {base}.main mn ON mt.recon_table_id = mn.recon_table_id "
            f"WHERE mn.recon_id = '{recon_id}' AND ("
            "mt.recon_metrics.row_comparison.missing_in_source > 0 OR "
            "mt.recon_metrics.row_comparison.missing_in_target > 0 OR "
            "mt.recon_metrics.column_comparison.absolute_mismatch > 0))"
        )
        return _int(rows[0].get("n")) if rows else 0
    except Exception:
        return -1  # unknown (metrics shape differs); render as '?'


def format_recon_runs(runs: list[dict[str, Any]]) -> str:
    """Render the runs as a skimmable markdown table for the user to choose from."""
    if not runs:
        return "No reconcile runs found. Run `databricks labs lakebridge reconcile` first."
    lines = [
        "### Recent Lakebridge reconcile runs",
        "",
        "| # | recon_id | Started | Table pairs | With diffs | Status |",
        "| --: | :-- | :-- | --: | --: | :-- |",
    ]
    for i, r in enumerate(runs, 1):
        diffs = r["tables_with_diffs"]
        diffs_cell = "?" if diffs < 0 else str(diffs)
        status = "✅ clean" if r.get("clean") else ("? " if diffs < 0 else "⚠️ has diffs")
        started = str(r.get("started") or "—")
        lines.append(
            f"| {i} | `{r['recon_id']}` | {started} | {r['table_pairs']} | {diffs_cell} | {status} |"
        )
    lines += ["", "_Pick a `recon_id` above to run the RCA._"]
    return "\n".join(lines)
