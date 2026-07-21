"""Tests for impact-based severity scoring and its use in the report."""

from __future__ import annotations

from rca_engine.models import Finding, Hypothesis, ReconType, RootCauseCategory, Verdict
from rca_engine.severity import severity_label, severity_score


def _finding(verdict: Verdict, *, mism: int, total: int,
             recon_type: ReconType = ReconType.COLUMN_MISMATCH, conf: float = 0.9) -> Finding:
    f = Finding(recon_id="r", source_table="s", target_table="t",
                recon_type=recon_type, column="c", mismatch_count=mism, total_count=total)
    f.hypotheses = [Hypothesis(category=RootCauseCategory.TYPE_PRECISION, verdict=verdict,
                               confidence=conf, rationale="x")]
    return f


def test_migration_outranks_benign_at_equal_blast_radius():
    mig = _finding(Verdict.MIGRATION_INDUCED, mism=50, total=100)
    ben = _finding(Verdict.BENIGN, mism=50, total=100)
    assert severity_score(mig) > severity_score(ben)


def test_blast_radius_increases_severity():
    small = _finding(Verdict.MIGRATION_INDUCED, mism=1, total=1000)
    large = _finding(Verdict.MIGRATION_INDUCED, mism=900, total=1000)
    assert severity_score(large) > severity_score(small)


def test_structural_findings_are_high_impact():
    schema = _finding(Verdict.MIGRATION_INDUCED, mism=1, total=0, recon_type=ReconType.SCHEMA)
    assert severity_label(schema) in {"High", "Medium"}


def test_labels_partition_the_range():
    assert severity_label(_finding(Verdict.MIGRATION_INDUCED, mism=1000, total=1000)) == "High"
    assert severity_label(_finding(Verdict.BENIGN, mism=1, total=1000)) == "Low"


def test_top_priorities_orders_by_severity_and_excludes_benign():
    from rca_engine.models import RcaResult
    from rca_engine.report import build_top_priorities

    high = _finding(Verdict.MIGRATION_INDUCED, mism=900, total=1000)
    high.column = "high_col"
    low = _finding(Verdict.MIGRATION_INDUCED, mism=1, total=1000)
    low.column = "low_col"
    benign = _finding(Verdict.BENIGN, mism=500, total=1000)
    benign.column = "benign_col"
    res = RcaResult(recon_id="r", dialect="snowflake", findings=[low, high, benign])
    md = build_top_priorities(res)
    assert md.index("high_col") < md.index("low_col")
    assert "benign_col" not in md
