"""Semi-structured (VARIANT/JSON) probes: key ordering and serialization."""

from __future__ import annotations

import json
from typing import Any

from rca_engine.models import RootCauseCategory
from rca_engine.probes import ProbeSignal


def _try_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def probe(source_value: Any, target_value: Any) -> list[ProbeSignal]:
    s = _try_json(source_value)
    t = _try_json(target_value)
    if s is None or t is None:
        return []

    # Semantically equal but textually different -> key ordering / whitespace / serialization.
    if s == t and str(source_value) != str(target_value):
        return [
            ProbeSignal(
                category=RootCauseCategory.SEMI_STRUCTURED,
                strength=0.9,
                detail="JSON/VARIANT payloads are semantically equal but serialized "
                "differently (key ordering or whitespace); representation-only difference.",
                meta={"semantically_equal": True},
            )
        ]

    # Same keys, different values -> a real content difference within the document.
    if isinstance(s, dict) and isinstance(t, dict) and set(s) == set(t) and s != t:
        changed = [k for k in s if s.get(k) != t.get(k)]
        return [
            ProbeSignal(
                category=RootCauseCategory.SEMI_STRUCTURED,
                strength=0.6,
                detail=f"JSON/VARIANT documents share keys but differ in values for {changed}.",
                meta={"changed_keys": changed, "semantically_equal": False},
            )
        ]
    return []
