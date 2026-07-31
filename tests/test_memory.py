"""Tests for the learning loop (memory): signatures, record, load, apply."""

from __future__ import annotations

from rca_engine.memory import (
    MemoryHit,
    apply_memory,
    load_memory,
    record_confirmations,
    signature_for,
)
from rca_engine.models import (
    Evidence,
    Finding,
    Hypothesis,
    MismatchSample,
    RcaResult,
    ReconType,
    RootCauseCategory,
    Verdict,
)
from rca_engine.report import _finding_section


class RecordingRunner:
    """Returns configured rows for SELECT; records all other statements."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed: list[str] = []

    def query(self, sql: str):
        if sql.strip().upper().startswith("SELECT"):
            return self.rows
        self.executed.append(sql)
        return []


def _finding(category, verdict, *, column="c", table="cat.sch.t",
             recon_type=ReconType.COLUMN_MISMATCH, evidence=None, confirmed=False) -> Finding:
    ev = list(evidence or [])
    if confirmed:
        ev.append(Evidence(label="drilldown", detail="confirmed", query="SELECT 1",
                           data={"confirmed": True, "n": 3}))
    f = Finding(recon_id="r1", source_table="cat.sch.s", target_table=table,
                recon_type=recon_type, column=column,
                samples=[MismatchSample(keys={"id": 1}, column=column, source_value="x", target_value="y")])
    f.hypotheses = [Hypothesis(category=category, verdict=verdict, confidence=0.8,
                               rationale="x", remediation="fix it", evidence=ev)]
    return f


# --------------------------------------------------------------------------- #
# Signatures
# --------------------------------------------------------------------------- #
def test_signature_uses_functions_then_scale_then_recon_type():
    fn = _finding(RootCauseCategory.TIMEZONE, Verdict.MIGRATION_INDUCED,
                  evidence=[Evidence(label="code", detail="d",
                                     data={"expr": "from_utc_timestamp(ts)", "functions": ["from_utc_timestamp"]})])
    assert signature_for(fn, "snowflake") == "snowflake|timezone|fn:from_utc_timestamp"

    scale = _finding(RootCauseCategory.TYPE_PRECISION, Verdict.MIGRATION_INDUCED,
                     evidence=[Evidence(label="code", detail="Source `c` is declared `DECIMAL(18,4)`.",
                                        data={"expr": "CAST(c AS DECIMAL(18,2))"})])
    assert signature_for(scale, "oracle") == "oracle|type_precision|scale:4->2"

    vol = _finding(RootCauseCategory.VOLUME_MISSING, Verdict.MIGRATION_INDUCED,
                   column=None, recon_type=ReconType.MISSING_IN_TARGET)
    assert signature_for(vol, "snowflake") == "snowflake|volume_missing|rt:missing_in_target"


# --------------------------------------------------------------------------- #
# Record
# --------------------------------------------------------------------------- #
def test_record_only_writes_confirmed_concluded_findings():
    confirmed = _finding(RootCauseCategory.TIMEZONE, Verdict.MIGRATION_INDUCED, confirmed=True)
    unconfirmed = _finding(RootCauseCategory.TIMEZONE, Verdict.MIGRATION_INDUCED, confirmed=False)
    review = _finding(RootCauseCategory.UNKNOWN, Verdict.NEEDS_REVIEW, confirmed=True)
    res = RcaResult(recon_id="r1", dialect="snowflake",
                    findings=[confirmed, unconfirmed, review])
    runner = RecordingRunner()
    n = record_confirmations(runner, "cat.sch.mem", res, "snowflake", run_by="me")
    assert n == 1
    inserts = [s for s in runner.executed if s.strip().upper().startswith("INSERT")]
    assert len(inserts) == 1 and "timezone" in inserts[0]


def test_record_noop_without_table():
    res = RcaResult(recon_id="r1", dialect="snowflake",
                    findings=[_finding(RootCauseCategory.TIMEZONE, Verdict.MIGRATION_INDUCED, confirmed=True)])
    assert record_confirmations(RecordingRunner(), "", res, "snowflake") == 0


# --------------------------------------------------------------------------- #
# Load + aggregate
# --------------------------------------------------------------------------- #
def test_load_aggregates_dominant_cause_per_signature():
    rows = [
        {"signature": "snowflake|timezone|fn:x", "category": "timezone", "verdict": "migration_induced",
         "remediation": "normalize tz", "recommended_owner": "eng", "confidence": 0.9,
         "example_location": "t.a"},
        {"signature": "snowflake|timezone|fn:x", "category": "timezone", "verdict": "migration_induced",
         "remediation": "", "recommended_owner": "", "confidence": 0.7, "example_location": "t.b"},
        {"signature": "snowflake|timezone|fn:x", "category": "upstream_drift", "verdict": "genuine_data",
         "remediation": "", "recommended_owner": "", "confidence": 0.6, "example_location": "t.c"},
    ]
    mem = load_memory(RecordingRunner(rows), "cat.sch.mem", dialect="snowflake")
    hit = mem["snowflake|timezone|fn:x"]
    assert hit.category == "timezone" and hit.verdict == "migration_induced"
    assert hit.hits == 3 and hit.confidence == 0.9 and hit.remediation == "normalize tz"


# --------------------------------------------------------------------------- #
# Apply (prior, never a verdict)
# --------------------------------------------------------------------------- #
def test_apply_proposes_category_for_unknown_but_stays_gated():
    unknown = _finding(RootCauseCategory.UNKNOWN, Verdict.NEEDS_REVIEW,
                       recon_type=ReconType.MISSING_IN_TARGET, column=None)
    sig = signature_for(unknown, "snowflake")
    mem = {sig: MemoryHit(signature=sig, category="volume_missing", verdict="migration_induced",
                          remediation="advance watermark", confidence=0.9, hits=4)}
    apply_memory([unknown], mem, "snowflake")
    proposed = unknown.top_hypothesis
    assert proposed.category == RootCauseCategory.VOLUME_MISSING
    assert proposed.verdict == Verdict.NEEDS_REVIEW      # gated: query must still confirm
    assert any(e.label == "memory" for e in proposed.evidence)


def test_apply_nudges_confidence_for_matching_known_finding():
    known = _finding(RootCauseCategory.TIMEZONE, Verdict.MIGRATION_INDUCED,
                     evidence=[Evidence(label="code", detail="d",
                                        data={"expr": "from_utc_timestamp(ts)", "functions": ["from_utc_timestamp"]})])
    sig = signature_for(known, "snowflake")
    before = known.top_hypothesis.confidence
    apply_memory([known], {sig: MemoryHit(signature=sig, category="timezone",
                                          verdict="migration_induced", confidence=0.9, hits=2)}, "snowflake")
    assert known.top_hypothesis.confidence > before
    assert any(e.label == "memory" for e in known.top_hypothesis.evidence)


def test_memory_evidence_renders_with_provenance_tag():
    f = _finding(RootCauseCategory.TIMEZONE, Verdict.MIGRATION_INDUCED)
    f.top_hypothesis.evidence.append(Evidence(label="memory", detail="Learned prior: seen 3x."))
    text = "\n".join("".join(c["source"]) for c in _finding_section(f))
    assert "Learned prior" in text and "📚 learned prior" in text
