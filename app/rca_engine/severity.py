"""Impact-based severity for a finding, so triage is by *business impact*, not
just classifier confidence.

Severity blends three signals:
- **Verdict** — a migration-induced defect outranks a benign/formatting diff.
- **Blast radius** — the fraction of rows affected (and structural findings such
  as schema/volume differences, which are inherently high-impact).
- **Confidence** — a well-confirmed high-impact finding ranks above a speculative one.

Returns a 0–100 score and a High/Medium/Low label used to order the report.
"""

from __future__ import annotations

from rca_engine.models import Finding, ReconType, Verdict

_VERDICT_WEIGHT = {
    Verdict.MIGRATION_INDUCED: 1.0,
    Verdict.NEEDS_REVIEW: 0.7,
    Verdict.GENUINE_DATA: 0.55,
    Verdict.BENIGN: 0.1,
}

# Structural findings have high blast radius regardless of the raw row fraction.
_STRUCTURAL = {ReconType.SCHEMA, ReconType.MISSING_IN_TARGET, ReconType.MISSING_IN_SOURCE}


def _affected_fraction(f: Finding) -> float:
    if f.total_count and f.total_count > 0:
        return max(0.0, min(1.0, f.mismatch_count / f.total_count))
    return 1.0 if f.mismatch_count else 0.0


def severity_score(f: Finding) -> int:
    """0–100 impact score for a finding."""
    top = f.top_hypothesis
    verdict = top.verdict if top else Verdict.NEEDS_REVIEW
    confidence = top.confidence if top else 0.5

    weight = _VERDICT_WEIGHT.get(verdict, 0.6)
    impact = _affected_fraction(f)
    if f.recon_type in _STRUCTURAL:
        impact = max(impact, 0.6)

    # Verdict dominates, blast radius modulates, confidence lightly scales.
    score = 100.0 * weight * (0.55 + 0.45 * impact) * (0.7 + 0.3 * confidence)
    return int(round(max(0.0, min(100.0, score))))


def severity_label(f: Finding) -> str:
    s = severity_score(f)
    if s >= 67:
        return "High"
    if s >= 34:
        return "Medium"
    return "Low"


def severity_badge(f: Finding) -> str:
    return {"High": "🔴 High", "Medium": "🟠 Medium", "Low": "🟢 Low"}[severity_label(f)]
