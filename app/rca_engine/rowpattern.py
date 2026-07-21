"""Row-pattern analysis for missing/extra rows.

Given the keys of missing (or extra) rows plus a dimension to bucket on, decide
whether the gap is clustered (e.g. a date range -> watermark/incremental lag or
a filter) or spread out (e.g. dedup/fan-out). This produces evidence the skill
turns into live drill-down queries.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass
class RowPatternResult:
    clustered: bool
    dominant_bucket: str | None
    concentration: float          # fraction of gap in the dominant bucket
    detail: str


def analyze_buckets(bucket_values: list[str]) -> RowPatternResult:
    """Decide whether missing/extra rows concentrate in one bucket."""

    if not bucket_values:
        return RowPatternResult(False, None, 0.0, "No rows to analyze.")

    counts = Counter(bucket_values)
    dominant, top = counts.most_common(1)[0]
    concentration = top / len(bucket_values)

    if concentration >= 0.6:
        return RowPatternResult(
            clustered=True,
            dominant_bucket=dominant,
            concentration=round(concentration, 2),
            detail=f"{concentration:.0%} of the gap concentrates in '{dominant}'; "
            f"suggests a bounded filter or watermark/incremental-load lag.",
        )
    return RowPatternResult(
        clustered=False,
        dominant_bucket=None,
        concentration=round(concentration, 2),
        detail="Gap is spread across buckets; suggests dedup/fan-out or a "
        "non-idempotent load rather than a single filter.",
    )
