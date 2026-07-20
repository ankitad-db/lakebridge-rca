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

    # Equal after rounding to the smaller scale -> precision/scale loss (e.g. DECIMAL->DOUBLE).
    min_scale = min(_scale(s), _scale(t))
    if min_scale > 0 or s != t:
        try:
            q = Decimal(1).scaleb(-min_scale) if min_scale > 0 else Decimal(1)
            if s.quantize(q) == t.quantize(q):
                signals.append(
                    ProbeSignal(
                        category=RootCauseCategory.TYPE_PRECISION,
                        strength=0.9,
                        detail=f"Values equal after rounding to scale {min_scale}; "
                        f"likely precision/scale loss (e.g. NUMBER(p,s) migrated to DOUBLE).",
                        meta={"source": str(s), "target": str(t), "scale": min_scale},
                    )
                )
        except InvalidOperation:
            pass

    # Tiny relative difference -> floating-point representation / summation order.
    denom = max(abs(s), abs(t))
    if denom != 0:
        rel = diff / denom
        if Decimal("0") < rel < Decimal("1e-6"):
            signals.append(
                ProbeSignal(
                    category=RootCauseCategory.TYPE_PRECISION,
                    strength=0.7,
                    detail=f"Very small relative difference ({rel:.2e}); "
                    f"consistent with float representation or aggregation ordering.",
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
