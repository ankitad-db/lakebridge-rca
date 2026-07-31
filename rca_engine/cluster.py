"""Collapse many findings that share one systemic root cause into clusters.

Migration defects are usually systemic: a single mis-translated ``CAST``, one
session timezone, or one load filter produces value mismatches across many
columns and tables. Reporting each column as its own finding buries the *one*
fix a reader must make. This pass groups findings by their confirmed mechanism so
the report can lead with "fix this one thing — it resolves N findings across M
columns", and so the long tail of near-identical findings stops dominating the page.

The grouping key is derived from the strongest available signal, in order:
1. the translated SQL functions on the target derivation (from code evidence) —
   table-agnostic, so the *same* bad translation clusters across tables;
2. a Lakebridge transpile warning message — also table-agnostic;
3. a fallback of ``(category, target_table)`` — e.g. one precision loss that hits
   many columns of the same table.

Only groups with two or more members become a cluster; isolated findings are left
to the normal per-finding report.
"""

from __future__ import annotations

from collections import Counter

from rca_engine.models import (
    Finding,
    RootCauseCategory,
    RootCauseCluster,
    Verdict,
)


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`") if name else name


def _loc(f: Finding) -> str:
    t = _short(f.target_table)
    return f"{t}.{f.column}" if f.column else t


def _signature(f: Finding) -> tuple[tuple[str, str], str]:
    """Return ``(group_key, human_label)`` for a finding's systemic mechanism.

    ``group_key`` is what findings are bucketed by; ``human_label`` is how the
    cluster is described. Code/transpile signals are table-agnostic (a shared
    translation defect spans tables); the fallback is scoped to one table.
    """

    top = f.top_hypothesis
    cat = top.category

    funcs: list[str] = []
    for e in top.evidence:
        if e.label == "code" and e.data and e.data.get("functions"):
            funcs = sorted({str(x).lower() for x in e.data["functions"] if x})
            break
    if funcs:
        fn = ", ".join(funcs)
        return (cat.value, "fn:" + fn), f"SQL translation via `{fn}`"

    tmsg = next((e.detail for e in top.evidence if e.label == "transpile"), None)
    if tmsg:
        return (cat.value, "tp:" + tmsg[:100]), f"Transpile: {tmsg}"

    # Fallback: same technical category concentrated in one target table.
    tbl = _short(f.target_table)
    return (cat.value, "tbl:" + f.target_table), f"`{cat.value}` across `{tbl}`"


def _dominant_verdict(findings: list[Finding]) -> Verdict:
    counts = Counter(f.top_hypothesis.verdict for f in findings if f.top_hypothesis)
    # Prefer an actionable verdict over NEEDS_REVIEW/BENIGN when it's present.
    for v in (Verdict.MIGRATION_INDUCED, Verdict.GENUINE_DATA):
        if counts.get(v):
            return v
    return counts.most_common(1)[0][0] if counts else Verdict.NEEDS_REVIEW


def build_clusters(findings: list[Finding], min_members: int = 2) -> list[RootCauseCluster]:
    """Group findings that share a systemic root cause. Returns clusters with two or
    more members, sorted by impact (finding count, then rows impacted)."""

    groups: dict[tuple[str, str], list[Finding]] = {}
    labels: dict[tuple[str, str], str] = {}
    for f in findings:
        if f.top_hypothesis is None or f.top_hypothesis.category == RootCauseCategory.UNKNOWN:
            continue
        key, label = _signature(f)
        groups.setdefault(key, []).append(f)
        labels.setdefault(key, label)

    clusters: list[RootCauseCluster] = []
    for key, members in groups.items():
        if len(members) < min_members:
            continue
        cat = members[0].top_hypothesis.category
        verdict = _dominant_verdict(members)
        # Remediation is shared by category, so any member's is representative; prefer a
        # member whose verdict matches the cluster's so the wording lines up.
        rep = next((m for m in members if m.top_hypothesis.verdict == verdict), members[0])
        clusters.append(
            RootCauseCluster(
                category=cat,
                verdict=verdict,
                signature=labels[key],
                remediation=rep.top_hypothesis.remediation,
                recommended_owner=rep.top_hypothesis.recommended_owner,
                members=[_loc(m) for m in members],
                tables=sorted({_short(m.target_table) for m in members}),
                finding_count=len(members),
                rows_impacted=sum(m.mismatch_count for m in members),
                confidence=round(max(m.top_hypothesis.confidence for m in members), 2),
            )
        )

    clusters.sort(key=lambda c: (c.finding_count, c.rows_impacted), reverse=True)
    return clusters
