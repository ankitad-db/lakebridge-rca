"""NULL/empty and boolean-representation probes."""

from __future__ import annotations

from typing import Any

from rca_engine.models import RootCauseCategory
from rca_engine.probes import ProbeSignal

# ``_null_recon_`` is Lakebridge's sentinel for a NULL value in details maps.
_NULLISH = {None, "", "null", "NULL", "None", "_null_recon_"}
_TRUE = {"y", "yes", "t", "true", "1", 1, True}
_FALSE = {"n", "no", "f", "false", "0", 0, False}


def _is_nullish(v: Any) -> bool:
    return v in _NULLISH


def _bool_token(v: Any) -> bool | None:
    key = v.lower() if isinstance(v, str) else v
    if key in _TRUE:
        return True
    if key in _FALSE:
        return False
    return None


def probe(source_value: Any, target_value: Any) -> list[ProbeSignal]:
    signals: list[ProbeSignal] = []

    s_null, t_null = _is_nullish(source_value), _is_nullish(target_value)

    # Both nullish but different textual representation (e.g. NULL vs empty string).
    if s_null and t_null:
        if str(source_value) != str(target_value):
            signals.append(
                ProbeSignal(
                    category=RootCauseCategory.NULL_BOOLEAN,
                    strength=0.85,
                    detail="One side NULL, other empty string; NULL-handling/representation "
                    "difference (map NULL/empty explicitly during load).",
                )
            )
        return signals

    # Exactly one side NULL/empty, the other has a real value -> likely a source data gap.
    if s_null != t_null:
        populated = "target" if s_null else "source"
        signals.append(
            ProbeSignal(
                category=RootCauseCategory.UPSTREAM_DRIFT,
                strength=0.8,
                detail=f"NULL/absent on one side but populated on the {populated}; "
                f"often a genuine source data gap rather than a migration defect.",
                meta={"populated_side": populated, "provenance_candidate": True},
            )
        )
        return signals

    # Boolean representation mismatch ('Y'/'N' vs true/false vs 1/0).
    sb, tb = _bool_token(source_value), _bool_token(target_value)
    if sb is not None and tb is not None and sb == tb and source_value != target_value:
        signals.append(
            ProbeSignal(
                category=RootCauseCategory.NULL_BOOLEAN,
                strength=0.85,
                detail="Equivalent boolean values with different representation "
                "(e.g. 'Y'/'N' vs true/false); boolean mapping difference.",
            )
        )
    return signals
