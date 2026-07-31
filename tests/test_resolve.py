"""Tests for the Tier-2 LLM fallback hook (rca_engine.resolve)."""

from __future__ import annotations

from rca_engine.models import (
    Finding,
    Hypothesis,
    MismatchSample,
    RcaResult,
    ReconType,
    RootCauseCategory,
    Verdict,
)
from rca_engine.resolve import (
    build_evidence_bundle,
    resolve_finding,
    unresolved_findings,
)


class StubRunner:
    """Returns a preset row for any query; records the SQL it was asked to run."""

    def __init__(self, row: dict | None = None, fail: bool = False):
        self.row = row
        self.fail = fail
        self.sql: list[str] = []

    def query(self, sql: str):
        self.sql.append(sql)
        if self.fail:
            raise RuntimeError("bad query")
        return [self.row] if self.row is not None else []


def _finding(verdict: Verdict, category: RootCauseCategory) -> Finding:
    return Finding(
        recon_id="r1",
        source_table="src.t",
        target_table="tgt.t",
        recon_type=ReconType.COLUMN_MISMATCH,
        column="amount",
        mismatch_count=3,
        total_count=100,
        samples=[MismatchSample(keys={"id": 1}, column="amount", source_value="1", target_value="2")],
        hypotheses=[
            Hypothesis(category=category, verdict=verdict, confidence=0.2, rationale="n/a")
        ],
    )


def test_unresolved_surfaces_needs_review_and_unknown_only():
    resolved = _finding(Verdict.MIGRATION_INDUCED, RootCauseCategory.TIMEZONE)
    needs = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.TYPE_PRECISION)
    unknown = _finding(Verdict.MIGRATION_INDUCED, RootCauseCategory.UNKNOWN)
    no_hyp = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.UNKNOWN)
    no_hyp.hypotheses = []

    res = RcaResult(recon_id="r1", dialect="snowflake", findings=[resolved, needs, unknown, no_hyp])
    out = unresolved_findings(res)
    assert resolved not in out
    assert needs in out and unknown in out and no_hyp in out


def test_resolve_promotes_when_query_confirms():
    f = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.UNKNOWN)
    runner = StubRunner(row={"confirmed": True, "n": 3})
    ok = resolve_finding(
        f, runner,
        category="timezone",
        rationale="constant +5h offset",
        confirm_query="SELECT true AS confirmed, 3 AS n",
    )
    assert ok is True
    top = f.top_hypothesis
    assert top.category == RootCauseCategory.TIMEZONE
    assert top.verdict == Verdict.MIGRATION_INDUCED   # inferred default for timezone
    assert top.confidence >= 0.6
    assert any(e.label == "llm_drilldown" and e.query for e in top.evidence)
    assert f.metadata["llm_fallback"] == "confirmed"


def test_resolve_respects_explicit_verdict():
    f = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.UNKNOWN)
    runner = StubRunner(row={"confirmed": 1})
    resolve_finding(
        f, runner,
        category="upstream_drift",
        verdict="genuine_data",
        rationale="source is NULL for these ids",
        confirm_query="SELECT 1 AS confirmed",
    )
    assert f.top_hypothesis.verdict == Verdict.GENUINE_DATA


def test_resolve_leaves_needs_review_when_not_confirmed():
    f = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.TYPE_PRECISION)
    runner = StubRunner(row={"confirmed": False, "n": 0})
    ok = resolve_finding(
        f, runner,
        category="timezone",
        rationale="maybe tz",
        confirm_query="SELECT false AS confirmed, 0 AS n",
    )
    assert ok is False
    assert f.top_hypothesis.verdict == Verdict.NEEDS_REVIEW
    assert f.metadata["llm_fallback"] == "not_confirmed"
    # the failed proposal is recorded as a next-check note
    assert any("NOT confirmed" in e.detail for e in f.top_hypothesis.evidence)


def test_resolve_is_safe_on_query_failure():
    f = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.UNKNOWN)
    runner = StubRunner(fail=True)
    ok = resolve_finding(
        f, runner,
        category="timezone",
        rationale="x",
        confirm_query="SELECT 1",
    )
    assert ok is False
    assert f.metadata["llm_fallback"] == "query_failed"


def test_build_evidence_bundle_shape():
    f = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.UNKNOWN)
    b = build_evidence_bundle(f, dialect="oracle")
    assert b["target_table"] == "tgt.t"
    assert b["column"] == "amount"
    assert b["dialect"] == "oracle"
    assert b["current_hypothesis"]["category"] == "unknown"
    assert len(b["samples"]) == 1 and b["samples"][0]["source_value"] == "1"


def test_build_evidence_bundle_surfaces_prior_and_attached_lineage():
    from rca_engine.models import Evidence

    f = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.UNKNOWN)
    f.top_hypothesis.evidence.extend([
        Evidence(label="code", detail="target casts to scale 2"),
        Evidence(label="lineage", detail="UC column lineage: `amount` derives from x.y.amt"),
    ])
    b = build_evidence_bundle(f)
    labels = [e["label"] for e in b["prior_evidence"]]
    assert "code" in labels and "lineage" in labels
    assert b["lineage"]["notes"] == ["UC column lineage: `amount` derives from x.y.amt"]


def test_build_evidence_bundle_live_lineage_fetch():
    # Runner returns column-lineage rows; the bundle should expose upstreams.
    row = {"src_tbl": "cat.sch.orders", "src_col": "amt", "tgt_col": "amount"}
    runner = StubRunner(row=row)
    f = _finding(Verdict.NEEDS_REVIEW, RootCauseCategory.UNKNOWN)
    b = build_evidence_bundle(f, runner=runner)
    assert "cat.sch.orders" in b["lineage"]["upstream_tables"]
    assert b["lineage"]["column_upstreams"] == ["cat.sch.orders.amt"]
