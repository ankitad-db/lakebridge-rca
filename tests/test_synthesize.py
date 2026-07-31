"""Tests for the LLM-synthesis layer: grounded narrative + broadened query coverage.

The synthesis layer must be *additive*: it can attach description and surface an
agent-generated query, but it can never set a verdict (that stays deterministic +
query-gated). These tests lock that contract in.
"""

from __future__ import annotations

from rca_engine.classify import classify_all
from rca_engine.cluster import build_clusters
from rca_engine.models import (
    Evidence,
    Finding,
    Hypothesis,
    MismatchSample,
    RcaResult,
    ReconType,
    RootCauseCategory,
    TableSummary,
    Verdict,
)
from rca_engine.report import _finding_section, build_notebook, build_tldr
from rca_engine.resolve import needs_query
from rca_engine.synthesize import build_narrative_context, set_narrative


def _num_finding(column: str, table: str, *, n: int = 5) -> Finding:
    s = [MismatchSample(keys={"id": i}, column=column, source_value="1.2345", target_value="1.23")
         for i in range(n)]
    return Finding(recon_id="r", source_table="src", target_table=table,
                   recon_type=ReconType.COLUMN_MISMATCH, column=column,
                   mismatch_count=n, total_count=100, samples=s)


def _result_with_summary() -> RcaResult:
    fs = classify_all([_num_finding("amount", "cat.sch.fact"),
                       _num_finding("price", "cat.sch.fact")])
    summ = [TableSummary(source_table="src.fact", target_table="cat.sch.fact",
                         source_count=100, target_count=100, absolute_mismatch=5,
                         mismatch_columns=["amount", "price"], join_keys=["id"])]
    return RcaResult(recon_id="r", dialect="snowflake", findings=fs,
                     table_summaries=summ, clusters=build_clusters(fs))


# --------------------------------------------------------------------------- #
# Narrative context + setter
# --------------------------------------------------------------------------- #
def test_context_is_factual_and_complete():
    ctx = build_narrative_context(_result_with_summary())
    assert ctx["recon_id"] == "r"
    assert ctx["verdict_counts"]  # concluded verdicts, read-only
    assert ctx["clusters"] and ctx["clusters"][0]["finding_count"] == 2
    tbl = ctx["tables"][0]
    assert tbl["target_table"] == "cat.sch.fact"
    assert tbl["findings"] and tbl["findings"][0]["category"] is not None
    # It's facts only: there is no field the agent could flip to change a stored verdict.
    assert "set_verdict" not in ctx


def test_set_narrative_overall_and_per_table_by_full_or_short_name():
    res = _result_with_summary()
    set_narrative(res, overall="Overall story.",
                  per_table={"fact": "Fact table story."})   # short name resolves
    assert res.narrative == "Overall story."
    assert res.table_summaries[0].narrative == "Fact table story."

    set_narrative(res, per_table={"cat.sch.fact": "Full-name story."})  # full name too
    assert res.table_summaries[0].narrative == "Full-name story."


def test_set_narrative_ignores_unknown_table_keys():
    res = _result_with_summary()
    set_narrative(res, per_table={"does.not.exist": "nope"})
    assert res.table_summaries[0].narrative == ""


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def test_tldr_renders_labeled_analyst_summary():
    res = _result_with_summary()
    assert "Analyst summary" not in build_tldr(res)  # absent until set
    set_narrative(res, overall="This run had one systemic cause.")
    md = build_tldr(res)
    assert "🧠 Analyst summary" in md
    assert "LLM synthesis" in md  # clearly labeled, not presented as evidence
    assert "This run had one systemic cause." in md


def test_notebook_renders_per_table_narrative():
    res = _result_with_summary()
    set_narrative(res, per_table={"fact": "Fact-specific paragraph."})
    src = "\n".join("".join(c["source"]) for c in build_notebook(res)["cells"])
    assert "Fact-specific paragraph." in src


def test_finding_section_surfaces_llm_query_and_provenance():
    f = _num_finding("amount", "cat.sch.fact")
    f.hypotheses = [Hypothesis(
        category=RootCauseCategory.STRING_FORMAT, verdict=Verdict.MIGRATION_INDUCED,
        confidence=0.9, rationale="agent-confirmed",
        evidence=[Evidence(label="llm_drilldown", detail="LLM confirmed via a live query.",
                           query="SELECT true AS confirmed, 5 AS n", data={"confirmed": True})],
    )]
    cells = _finding_section(f)
    text = "\n".join("".join(c["source"]) for c in cells)
    assert "SELECT true AS confirmed" in text          # LLM query pre-filled into the cell
    assert "Evidence (LLM query)" in text
    assert "🧠 LLM synthesis" in text                   # provenance tag


# --------------------------------------------------------------------------- #
# Broadened query coverage
# --------------------------------------------------------------------------- #
def _finding_with(category, verdict, *, evidence=None) -> Finding:
    f = Finding(recon_id="r", source_table="s", target_table="t",
                recon_type=ReconType.COLUMN_MISMATCH, column="c")
    f.hypotheses = [Hypothesis(category=category, verdict=verdict, confidence=0.7,
                               rationale="x", evidence=evidence or [])]
    return f


def test_needs_query_selects_generic_and_residual_skips_confirmed():
    confirmed = _finding_with(
        RootCauseCategory.TYPE_PRECISION, Verdict.MIGRATION_INDUCED,
        evidence=[Evidence(label="drilldown", detail="confirmed", query="SELECT 1", data={"confirmed": True})],
    )
    no_query = _finding_with(RootCauseCategory.TYPE_PRECISION, Verdict.MIGRATION_INDUCED)  # generic template
    unknown = _finding_with(RootCauseCategory.UNKNOWN, Verdict.NEEDS_REVIEW)

    picked = needs_query([confirmed, no_query, unknown])
    assert confirmed not in picked          # already has a deterministic confirming query
    assert no_query in picked and unknown in picked
