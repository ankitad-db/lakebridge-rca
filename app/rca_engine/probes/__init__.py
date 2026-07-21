"""Deterministic value-difference probes.

Each probe inspects a (source_value, target_value) pair and returns zero or more
``ProbeSignal`` objects. Signals are evidence-bearing hints, not verdicts; the
classifier combines them with the knowledge base to decide a root cause.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rca_engine.models import RootCauseCategory


@dataclass
class ProbeSignal:
    """A hint that a specific mechanism explains a value difference."""

    category: RootCauseCategory
    # How strongly this probe fired, in [0, 1].
    strength: float
    detail: str
    meta: dict[str, Any] = field(default_factory=dict)


from rca_engine.probes import complex as complex_probe  # noqa: E402
from rca_engine.probes import nullbool, numeric, string, temporal  # noqa: E402

ALL_PROBES = [
    numeric.probe,
    temporal.probe,
    string.probe,
    nullbool.probe,
    complex_probe.probe,
]


def run_all(source_value: Any, target_value: Any) -> list[ProbeSignal]:
    """Run every probe against a value pair and collect the signals."""

    signals: list[ProbeSignal] = []
    for probe in ALL_PROBES:
        try:
            signals.extend(probe(source_value, target_value))
        except Exception:  # a probe must never break the pipeline
            continue
    return signals


__all__ = ["ProbeSignal", "run_all", "ALL_PROBES"]
