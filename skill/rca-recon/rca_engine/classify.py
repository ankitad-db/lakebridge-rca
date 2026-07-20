"""Combine probe signals, row patterns, and the KB into ranked hypotheses.

This is the deterministic first pass. The Genie Code skill layers live queries
on top to raise confidence or resolve NEEDS_REVIEW findings.
"""

from __future__ import annotations

from collections import defaultdict

from rca_engine.knowledge import KnowledgeBase, load_kb
from rca_engine.models import (
    Evidence,
    Finding,
    Hypothesis,
    ReconType,
    RootCauseCategory,
    Verdict,
)
from rca_engine.probes import ProbeSignal, run_all

# Which categories map to which verdict by default.
_MIGRATION = {
    RootCauseCategory.TYPE_PRECISION,
    RootCauseCategory.TIMEZONE,
    RootCauseCategory.TRANSPILATION,
    RootCauseCategory.VOLUME_MISSING,
    RootCauseCategory.VOLUME_EXTRA,
    RootCauseCategory.NULL_BOOLEAN,
    RootCauseCategory.STRING_FORMAT,   # the transform altered the value (case/whitespace); may be low-severity
    RootCauseCategory.ENV_CONFIG,
}
_GENUINE = {RootCauseCategory.UPSTREAM_DRIFT}
# Only truly semantically-equal differences (e.g. JSON key reordering) are benign.
_COSMETIC = {RootCauseCategory.SEMI_STRUCTURED}

_NEEDS_REVIEW_THRESHOLD = 0.5


def _verdict_for(category: RootCauseCategory, strength: float, provenance: bool) -> Verdict:
    if provenance or category in _GENUINE:
        return Verdict.GENUINE_DATA
    if category in _COSMETIC:
        # Representation-only differences are benign when the probe is confident.
        return Verdict.BENIGN if strength >= 0.8 else Verdict.NEEDS_REVIEW
    if category in _MIGRATION:
        return Verdict.MIGRATION_INDUCED if strength >= _NEEDS_REVIEW_THRESHOLD else Verdict.NEEDS_REVIEW
    return Verdict.NEEDS_REVIEW


def _classify_column_mismatch(finding: Finding, kb: KnowledgeBase) -> list[Hypothesis]:
    # Aggregate probe signals across all sampled value pairs.
    agg: dict[RootCauseCategory, list[ProbeSignal]] = defaultdict(list)
    provenance = False
    for sample in finding.samples:
        for sig in run_all(sample.source_value, sample.target_value):
            agg[sig.category].append(sig)
            if sig.meta.get("provenance_candidate"):
                provenance = True

    hypotheses: list[Hypothesis] = []
    for category, signals in agg.items():
        # Confidence: mean strength scaled by fraction of samples that fired.
        mean_strength = sum(s.strength for s in signals) / len(signals)
        coverage = len(signals) / max(len(finding.samples), 1)
        confidence = round(min(mean_strength * (0.5 + 0.5 * coverage), 0.99), 2)
        verdict = _verdict_for(category, mean_strength, provenance)
        hypotheses.append(
            Hypothesis(
                category=category,
                verdict=verdict,
                confidence=confidence,
                rationale=signals[0].detail,
                remediation=kb.remediation_for(category.value),
                recommended_owner="data owner / source team"
                if verdict == Verdict.GENUINE_DATA
                else "migration engineer",
                evidence=[Evidence(label="probe", detail=s.detail, data=s.meta) for s in signals[:3]],
            )
        )

    if not hypotheses:
        hypotheses.append(
            Hypothesis(
                category=RootCauseCategory.UNKNOWN,
                verdict=Verdict.NEEDS_REVIEW,
                confidence=0.2,
                rationale="No deterministic probe fired; requires a live drill-down query.",
                recommended_owner="migration engineer",
            )
        )
    return sorted(hypotheses, key=lambda h: h.confidence, reverse=True)


def _classify_volume(finding: Finding, kb: KnowledgeBase) -> list[Hypothesis]:
    if finding.recon_type == ReconType.MISSING_IN_TARGET:
        category = RootCauseCategory.VOLUME_MISSING
        rationale = (
            f"{finding.mismatch_count} row(s) present in source but missing in target; "
            f"check load filter/watermark, or a genuine source-only population."
        )
    else:
        category = RootCauseCategory.VOLUME_EXTRA
        rationale = (
            f"{finding.mismatch_count} row(s) present in target but not source; "
            f"check fan-out joins or non-idempotent loads producing duplicates."
        )
    return [
        Hypothesis(
            category=category,
            verdict=Verdict.MIGRATION_INDUCED,
            confidence=0.6,
            rationale=rationale,
            remediation=kb.remediation_for(category.value),
            recommended_owner="migration engineer",
            evidence=[Evidence(label="row_counts", detail=rationale)],
        )
    ]


def _classify_schema(finding: Finding, kb: KnowledgeBase) -> list[Hypothesis]:
    return [
        Hypothesis(
            category=RootCauseCategory.TYPE_PRECISION,
            verdict=Verdict.MIGRATION_INDUCED,
            confidence=0.7,
            rationale="Schema/type difference reported by reconcile; verify the type mapping.",
            remediation=kb.remediation_for(RootCauseCategory.TYPE_PRECISION.value),
            recommended_owner="migration engineer",
        )
    ]


def classify_finding(finding: Finding, kb: KnowledgeBase) -> Finding:
    if finding.recon_type == ReconType.COLUMN_MISMATCH:
        finding.hypotheses = _classify_column_mismatch(finding, kb)
    elif finding.recon_type in (ReconType.MISSING_IN_TARGET, ReconType.MISSING_IN_SOURCE):
        finding.hypotheses = _classify_volume(finding, kb)
    elif finding.recon_type == ReconType.SCHEMA:
        finding.hypotheses = _classify_schema(finding, kb)
    return finding


def _freshness_pass(findings: list[Finding], kb: KnowledgeBase) -> None:
    """Table-level inference: if a table shows timestamp-based snapshot drift,
    treat its remaining *unexplained, partial* column mismatches as likely
    genuine upstream drift (a stale snapshot affects a subset of rows) rather
    than migration defects. The live drill-down confirms."""

    stale_tables = {
        f.target_table
        for f in findings
        if f.recon_type == ReconType.COLUMN_MISMATCH
        and f.top_hypothesis is not None
        and f.top_hypothesis.category == RootCauseCategory.UPSTREAM_DRIFT
    }
    for f in findings:
        if f.target_table not in stale_tables or f.recon_type != ReconType.COLUMN_MISMATCH:
            continue
        top = f.top_hypothesis
        is_unexplained = top is None or top.category == RootCauseCategory.UNKNOWN
        is_partial = 0 <= f.mismatch_count < (f.total_count or 0)
        if is_unexplained and is_partial:
            f.hypotheses = [
                Hypothesis(
                    category=RootCauseCategory.UPSTREAM_DRIFT,
                    verdict=Verdict.GENUINE_DATA,
                    confidence=0.55,
                    rationale=f"`{f.column}` differs on a subset of rows in a table that shows "
                    f"snapshot/load-time drift; likely a genuine upstream data difference. "
                    f"Confirm with a live drill-down before actioning.",
                    remediation=kb.remediation_for(RootCauseCategory.UPSTREAM_DRIFT.value),
                    recommended_owner="data owner / source team",
                    evidence=[Evidence(label="freshness", detail="table has timestamp snapshot drift")],
                )
            ]


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`").lower() if name else ""


def _code_correlation_pass(findings: list[Finding], mapping: dict) -> None:
    """Confirm/deny a mismatch's cause using the Lakebridge transpile artifacts.

    Adds code-level evidence (the exact target derivation / load filter / transpile
    warning) and adjusts confidence: a direct passthrough rules out transpilation;
    a derived column corroborates it; a load filter explains missing rows.
    """

    for f in findings:
        tm = mapping.get(_short(f.target_table))
        if tm is None:
            continue
        top = f.top_hypothesis
        if top is None:
            continue

        if f.recon_type == ReconType.COLUMN_MISMATCH and f.column:
            ct = tm.transform_for(f.column)
            if ct is None:
                continue
            if ct.is_direct:
                top.evidence.append(Evidence(
                    label="code",
                    detail=f"Target `{f.column}` is a direct passthrough (no transform); a code "
                    f"translation (transpilation) cause is ruled out — the difference is a "
                    f"type/precision or upstream-data issue.",
                ))
                if top.category == RootCauseCategory.TRANSPILATION:
                    top.confidence = round(top.confidence * 0.6, 2)
            else:
                top.evidence.insert(0, Evidence(
                    label="code",
                    detail=f"Target derivation: `{ct.expr}`"
                    + (f" (functions: {', '.join(ct.functions)})" if ct.functions else ""),
                    data={"functions": ct.functions, "expr": ct.expr},
                ))
                top.confidence = round(min(0.99, max(top.confidence, 0.6) + 0.1), 2)
                if f.column.lower() not in ct.expr.lower():
                    f.metadata["code_generated"] = True
                    top.evidence.append(Evidence(
                        label="code",
                        detail=f"Target `{f.column}` is generated by the transform and not carried "
                        f"from the same-named source column; the value is migration-produced. "
                        f"Decide if this is an intended audit/derived column or a defect "
                        f"(it can never match source, so this is flagged needs-review).",
                    ))
                    # A generated value contradicts a "genuine upstream data" verdict: the
                    # target fabricates it. If already marked genuine, pull it back to review;
                    # the drill-down also refuses to promote it (see drilldown.py).
                    if top.verdict == Verdict.GENUINE_DATA:
                        top.verdict = Verdict.NEEDS_REVIEW
                    top.recommended_owner = "migration engineer + data owner (decide)"
                    top.remediation = (
                        f"`{f.column}` is computed by the transform, so it will never equal the "
                        f"source. Decide whether it is an intended derived/audit column (exclude "
                        f"it from recon or add a tolerance) or a genuine defect (fix the "
                        f"transform to carry the source value)."
                    )
            for iss in tm.transpile_issues:
                top.evidence.append(Evidence(
                    label="transpile",
                    detail=f"Lakebridge transpile {iss.severity}/{iss.kind}: {iss.message}",
                ))

        elif f.recon_type == ReconType.MISSING_IN_TARGET and tm.target_filter:
            top.evidence.insert(0, Evidence(
                label="code",
                detail=f"Transform applies a load filter `WHERE {tm.target_filter}`, which explains "
                f"the rows missing in target (watermark/filter).",
            ))
            top.confidence = round(min(0.95, max(top.confidence, 0.6) + 0.2), 2)


def classify_all(findings: list[Finding], dialect: str = "snowflake", mapping: dict | None = None) -> list[Finding]:
    kb = load_kb(dialect)
    classified = [classify_finding(f, kb) for f in findings]
    _freshness_pass(classified, kb)
    if mapping:
        _code_correlation_pass(classified, mapping)
    return classified
