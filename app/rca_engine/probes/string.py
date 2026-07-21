"""String probes: case, whitespace, and collation/normalization differences."""

from __future__ import annotations

import unicodedata
from typing import Any

from rca_engine.models import RootCauseCategory
from rca_engine.probes import ProbeSignal


def probe(source_value: Any, target_value: Any) -> list[ProbeSignal]:
    if not isinstance(source_value, str) or not isinstance(target_value, str):
        return []
    if source_value == target_value:
        return []

    signals: list[ProbeSignal] = []

    if source_value.strip() == target_value.strip():
        signals.append(
            ProbeSignal(
                category=RootCauseCategory.STRING_FORMAT,
                strength=0.9,
                detail="Values equal after trimming; leading/trailing whitespace difference "
                "(e.g. CHAR padding or missing TRIM in the transform).",
            )
        )
        return signals

    if source_value.casefold() == target_value.casefold():
        signals.append(
            ProbeSignal(
                category=RootCauseCategory.STRING_FORMAT,
                strength=0.85,
                detail="Values equal after case-folding; case difference "
                "(Snowflake identifier upper-casing or collation).",
            )
        )
        return signals

    def norm(x: str) -> str:
        return unicodedata.normalize("NFC", x).strip().casefold()

    if norm(source_value) == norm(target_value):
        signals.append(
            ProbeSignal(
                category=RootCauseCategory.STRING_FORMAT,
                strength=0.8,
                detail="Values equal after Unicode NFC + trim + case-fold; "
                "collation/encoding normalization difference.",
            )
        )
    return signals
