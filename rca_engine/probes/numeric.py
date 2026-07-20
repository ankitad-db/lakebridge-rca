"""Numeric probes: precision/scale, rounding, and constant-factor differences."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from rca_engine.models import RootCauseCategory
from rca_engine.probes import ProbeSignal


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _scale(d: Decimal) -> int:
    exp = d.normalize().as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def probe(source_value: Any, target_value: Any) -> list[ProbeSignal]:
    s = _to_decimal(source_value)
    t = _to_decimal(target_value)
    if s is None or t is None:
        return []
    if s == t:
        return []

    signals: list[ProbeSignal] = []
    diff = abs(s - t)
    denom = max(abs(s), abs(t))
    rel = (diff / denom) if denom != 0 else Decimal(0)
    precision_fired = False

    # Equal after rounding to the smaller scale -> precision/scale loss (e.g. DECIMAL->DOUBLE).
    min_scale = min(_scale(s), _scale(t))
    try:
        q = Decimal(1).scaleb(-min_scale) if min_scale > 0 else Decimal(1)
        if s.quantize(q) == t.quantize(q):
            precision_fired = True
            if min_scale == 0 and _scale(s) > 0:
                # Source has decimals but target is whole -> rounding to whole units,
                # typically a ROUND() precision/rounding-mode difference in the transform.
                signals.append(
                    ProbeSignal(
                        category=RootCauseCategory.TRANSPILATION,
                        strength=0.85,
                        detail="Target equals source rounded to whole units; consistent with a "
                        "ROUND() precision/rounding-mode difference in the translated aggregation.",
                        meta={"source": str(s), "target": str(t), "scale": min_scale},
                    )
                )
            else:
                signals.append(
                    ProbeSignal(
                        category=RootCauseCategory.TYPE_PRECISION,
                        strength=0.9,
                        detail=f"Values equal after rounding to scale {min_scale}; "
                        f"likely precision/scale loss (e.g. NUMBER(p,s) migrated to a lower scale/DOUBLE).",
                        meta={"source": str(s), "target": str(t), "scale": min_scale},
                    )
                )
    except InvalidOperation:
        pass

    # Relative-difference interpretations (only if not already explained by scale loss).
    if not precision_fired and denom != 0:
        target_is_whole = t == t.to_integral_value()
        source_is_whole = s == s.to_integral_value()
        if target_is_whole and not source_is_whole and rel < Decimal("0.05"):
            # Target rounded to whole units while source keeps decimals -> ROUND()
            # rounding-mode/precision difference in the translated aggregation.
            signals.append(
                ProbeSignal(
                    category=RootCauseCategory.TRANSPILATION,
                    strength=0.72,
                    detail="Target is rounded to whole units while source has a fractional part; "
                    "consistent with a ROUND() precision/rounding-mode difference in the transform.",
                    meta={"source": str(s), "target": str(t), "relative_diff": str(rel)},
                )
            )
        elif Decimal("0") < rel < Decimal("1e-6"):
            signals.append(
                ProbeSignal(
                    category=RootCauseCategory.TYPE_PRECISION,
                    strength=0.7,
                    detail=f"Very small relative difference ({rel:.2e}); "
                    f"consistent with float representation or aggregation ordering.",
                    meta={"relative_diff": str(rel)},
                )
            )
        elif Decimal("0") < rel < Decimal("1e-3"):
            signals.append(
                ProbeSignal(
                    category=RootCauseCategory.TYPE_PRECISION,
                    strength=0.6,
                    detail=f"Small relative difference ({rel:.2e}); likely rounding or scale loss.",
                    meta={"relative_diff": str(rel)},
                )
            )

    # Clean constant factor (10x, 100x, unit change) -> cast/units bug.
    if t != 0:
        ratio = s / t
        for factor in (Decimal(10), Decimal(100), Decimal(1000), Decimal("0.1"), Decimal("0.01")):
            if ratio == factor:
                signals.append(
                    ProbeSignal(
                        category=RootCauseCategory.TRANSPILATION,
                        strength=0.6,
                        detail=f"Source is exactly {factor}x target; possible unit/scale "
                        f"or cast error in the transformation.",
                        meta={"factor": str(factor)},
                    )
                )
                break

    return signals
