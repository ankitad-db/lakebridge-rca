"""Scan scoping — keep RCA's confirming/enrichment queries cheap on large tables.

The deterministic first pass and the sampled example rows are cheap (they read the
already-computed recon output). The *live* confirming, drift, and fix-validation queries,
however, aggregate over the source and target tables. Left unbounded they full-scan both
sides — fine on a test bed, expensive on a production warehouse.

``ScanScope`` bounds those scans two ways, both **exact** (no approximation):

1. **Confirm on the flagged keys** — a column-mismatch confirming query only needs to
   re-check the rows the reconciliation already flagged. ``key_in_clause`` turns the
   sampled mismatch keys into an ``IN (...)`` predicate, so the join is bounded to those
   keys (predicate push-down) instead of scanning the whole table. The *total* mismatch
   count still comes from the recon metrics, so nothing is under-reported.
2. **Partition / date scoping** — ``partition_clause`` restricts full-table aggregates
   (drift, watermark, distinct counts) to the reconciled window, e.g. the load partition,
   so a distribution/volume check reads one partition instead of full history.

``mode="full"`` disables both (the original behavior). Everything degrades safely: if there
are no sampled keys or no partition column, the clause is simply empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ScanScope:
    """How aggressively to bound the live source/target scans.

    - ``mode``: ``"scoped"`` (bound to flagged keys + partition window) or ``"full"``.
    - ``partition_column``: a column present on *both* source and target used to restrict
      full-table aggregates to a window (typically the load/ingest date or partition key).
    - ``date_start`` / ``date_end``: the inclusive window for ``partition_column``.
    - ``max_keys``: cap on how many flagged keys go into an ``IN (...)`` predicate (keeps
      the generated SQL bounded; the recon metrics still hold the true total count).
    """

    mode: str = "scoped"
    partition_column: str = ""
    date_start: str = ""
    date_end: str = ""
    max_keys: int = 500

    @property
    def scoped(self) -> bool:
        return self.mode == "scoped"


def _lit(v: Any) -> str:
    """Render a Python value as a safe SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _sample_keys(finding: Any) -> list[str]:
    for s in getattr(finding, "samples", []) or []:
        if getattr(s, "keys", None):
            return list(s.keys.keys())
    return []


def key_in_clause(finding: Any, scope: ScanScope | None, alias: str = "s") -> str:
    """Predicate binding a join/scan to the sampled mismatch keys (empty if not possible).

    Single key → ``s.`id` IN (1, 2, 3)``. Composite key → an OR of AND-ed equalities over
    the distinct sampled key tuples. Returns ``""`` when scoping is off, there are no
    sampled keys, or the samples carry no key values."""

    if scope is None or not scope.scoped:
        return ""
    keys = _sample_keys(finding)
    if not keys:
        return ""

    # Collect distinct key tuples from the samples, capped at max_keys.
    seen: set[tuple] = set()
    tuples: list[tuple] = []
    for s in finding.samples:
        if not getattr(s, "keys", None):
            continue
        try:
            tup = tuple(s.keys[k] for k in keys)
        except KeyError:
            continue
        if tup in seen:
            continue
        seen.add(tup)
        tuples.append(tup)
        if len(tuples) >= max(1, scope.max_keys):
            break
    if not tuples:
        return ""

    if len(keys) == 1:
        vals = ", ".join(_lit(t[0]) for t in tuples)
        return f"{alias}.`{keys[0]}` IN ({vals})"

    ors = [
        "(" + " AND ".join(f"{alias}.`{k}` = {_lit(v)}" for k, v in zip(keys, tup)) + ")"
        for tup in tuples
    ]
    return "(" + " OR ".join(ors) + ")"


def partition_clause(scope: ScanScope | None, alias: str = "") -> str:
    """``<col> BETWEEN start AND end`` for the configured partition/date window (or "")."""
    if scope is None or not scope.scoped:
        return ""
    if not (scope.partition_column and scope.date_start and scope.date_end):
        return ""
    col = f"{alias}.`{scope.partition_column}`" if alias else f"`{scope.partition_column}`"
    return f"{col} BETWEEN {_lit(scope.date_start)} AND {_lit(scope.date_end)}"


def and_clauses(*clauses: str) -> str:
    """Join non-empty predicates with AND (prefixed with AND when any exist)."""
    parts = [c for c in clauses if c]
    return (" AND " + " AND ".join(parts)) if parts else ""


def where_clauses(*clauses: str) -> str:
    """Build a leading ``WHERE ...`` from non-empty predicates (or "")."""
    parts = [c for c in clauses if c]
    return (" WHERE " + " AND ".join(parts)) if parts else ""
