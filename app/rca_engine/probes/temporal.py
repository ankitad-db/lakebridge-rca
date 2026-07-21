"""Temporal probes: timezone offset shifts and precision truncation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rca_engine.models import RootCauseCategory
from rca_engine.probes import ProbeSignal

_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d",
)

# Common whole-hour offsets (seconds) seen with TIMESTAMP_LTZ vs UTC.
_COMMON_OFFSETS = {
    1800, 3600, 7200, 10800, 12600, 14400, 16200, 18000, 19800, 21600,
    25200, 28800, 32400, 36000, 39600, 43200, -18000, -21600, -25200, -28800,
}


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def probe(source_value: Any, target_value: Any) -> list[ProbeSignal]:
    s = _parse(source_value)
    t = _parse(target_value)
    if s is None or t is None:
        return []
    if s.tzinfo != t.tzinfo:
        # Normalize naive for delta math.
        s = s.replace(tzinfo=None)
        t = t.replace(tzinfo=None)
    if s == t:
        return []

    signals: list[ProbeSignal] = []
    delta = abs((s - t).total_seconds())

    # Date-only values (no time component) that differ by a small whole number of days
    # point to a date-bucketing/week-start config difference (e.g. DATE_TRUNC('week')
    # Sunday vs Monday), not a timezone offset.
    date_only = ":" not in str(source_value) and ":" not in str(target_value)
    if date_only and delta % 86400 == 0 and 0 < delta <= 6 * 86400:
        return [
            ProbeSignal(
                category=RootCauseCategory.ENV_CONFIG,
                strength=0.75,
                detail=f"Date differs by {int(delta // 86400)} whole day(s) with no time "
                f"component; likely a week-start/date-bucketing config difference "
                f"(e.g. DATE_TRUNC week start Sunday vs Monday, or session calendar).",
                meta={"days": int(delta // 86400)},
            )
        ]

    if delta in _COMMON_OFFSETS or (delta % 3600 == 0 and 0 < delta < 86400):
        signals.append(
            ProbeSignal(
                category=RootCauseCategory.TIMEZONE,
                strength=0.9,
                detail=f"Constant offset of {delta/3600:.1f}h between source and target; "
                f"likely TIMESTAMP_LTZ/TZ vs UTC normalization difference.",
                meta={"offset_seconds": delta},
            )
        )
    elif 0 < delta < 1:
        signals.append(
            ProbeSignal(
                category=RootCauseCategory.TYPE_PRECISION,
                strength=0.7,
                detail="Sub-second difference; likely timestamp precision truncation "
                "(nanoseconds -> microseconds).",
                meta={"offset_seconds": delta},
            )
        )
    elif delta >= 86400:
        signals.append(
            ProbeSignal(
                category=RootCauseCategory.UPSTREAM_DRIFT,
                strength=0.65,
                detail=f"Large time shift (~{delta/86400:.1f}d) between source and target; "
                f"points to a snapshot/load-time (freshness) difference rather than code translation.",
                meta={"offset_seconds": delta, "provenance_candidate": True},
            )
        )
    return signals
