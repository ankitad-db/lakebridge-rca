"""Tests for the Tier-2 Foundation Model fallback (rca_engine.llm_fallback).

The App/CLI/skill all delegate to this one implementation. The model call itself is
monkeypatched — we verify the loop wiring and the query-confirmation gate (a proposal is
only promoted when its query confirms). A dummy ``client`` is passed so no WorkspaceClient
is built.
"""

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
from rca_engine import llm_fallback

_CLIENT = object()  # dummy client so run_llm_fallback skips building a WorkspaceClient


class StubRunner:
    def __init__(self, row: dict | None = None):
        self.row = row
        self.sql: list[str] = []

    def query(self, sql: str):
        self.sql.append(sql)
        return [self.row] if self.row is not None else []


def _residual_result() -> RcaResult:
    f = Finding(
        recon_id="r1", source_table="src.t", target_table="tgt.t",
        recon_type=ReconType.COLUMN_MISMATCH, column="region",
        mismatch_count=5, total_count=100,
        samples=[MismatchSample(keys={"id": 1}, column="region",
                                source_value="APAC", target_value="Apac")],
        hypotheses=[Hypothesis(category=RootCauseCategory.UNKNOWN,
                               verdict=Verdict.NEEDS_REVIEW, confidence=0.2, rationale="n/a")],
    )
    return RcaResult(recon_id="r1", dialect="snowflake", findings=[f])


def test_extract_json_handles_fenced_and_prose():
    assert llm_fallback._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm_fallback._extract_json('sure: {"resolvable": true}') == {"resolvable": True}
    assert llm_fallback._extract_json("no json here") is None


def test_run_llm_fallback_promotes_on_confirm(monkeypatch):
    result = _residual_result()
    runner = StubRunner(row={"confirmed": True, "n": 5})

    monkeypatch.setattr(llm_fallback, "_ask_model", lambda client, ep, bundle: {
        "resolvable": True, "category": "string_format", "verdict": "migration_induced",
        "rationale": "equal after UPPER()", "confirm_query": "SELECT true AS confirmed, 5 AS n",
    })

    promoted = llm_fallback.run_llm_fallback(result, runner, endpoint="fm-endpoint", client=_CLIENT)
    assert promoted == 1
    assert result.findings[0].top_hypothesis.category == RootCauseCategory.STRING_FORMAT
    assert result.findings[0].top_hypothesis.verdict == Verdict.MIGRATION_INDUCED


def test_run_llm_fallback_skips_when_not_resolvable(monkeypatch):
    result = _residual_result()
    runner = StubRunner(row={"confirmed": True})
    monkeypatch.setattr(llm_fallback, "_ask_model", lambda client, ep, bundle: {"resolvable": False})
    assert llm_fallback.run_llm_fallback(result, runner, endpoint="fm-endpoint", client=_CLIENT) == 0
    assert result.findings[0].top_hypothesis.verdict == Verdict.NEEDS_REVIEW


def test_run_llm_fallback_noop_without_endpoint():
    result = _residual_result()
    assert llm_fallback.run_llm_fallback(result, StubRunner(), endpoint="") == 0
