"""Freshness / snapshot-skew check.

Compares a source extract time with a target load time. A material gap makes
"upstream drift" (a genuine data difference) a likely explanation for value
mismatches, as opposed to a migration defect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class FreshnessResult:
    skewed: bool
    gap_seconds: float
    detail: str


def compare(source_extract: datetime | None, target_load: datetime | None,
            threshold_seconds: float = 3600) -> FreshnessResult:
    if source_extract is None or target_load is None:
        return FreshnessResult(False, 0.0, "Extract/load timestamps unavailable.")
    gap = abs((target_load - source_extract).total_seconds())
    if gap >= threshold_seconds:
        return FreshnessResult(
            skewed=True,
            gap_seconds=gap,
            detail=f"Source extract and target load are {gap/3600:.1f}h apart; "
            f"value mismatches may reflect upstream data drift, not migration logic.",
        )
    return FreshnessResult(False, gap, "Snapshots are close in time; skew unlikely.")
