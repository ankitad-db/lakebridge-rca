"""Tests for deterministic suggested-fix generation."""

from __future__ import annotations

from rca_engine.fixgen import (
    build_fix,
    generate_fixes,
    validate_all_fixes,
    validate_fix,
)
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
from rca_engine.report import build_notebook, build_tldr


def _finding(category, *, column="c", recon_type=ReconType.COLUMN_MISMATCH,
             evidence=None, keys=("id",), table="cat.sch.t") -> Finding:
    samples = [MismatchSample(keys={k: 1 for k in keys}, column=column,
                              source_value="x", target_value="y")]
    f = Finding(recon_id="r", source_table="cat.sch.s", target_table=table,
                recon_type=recon_type, column=column, mismatch_count=3, total_count=100,
                samples=samples)
    f.hypotheses = [Hypothesis(category=category, verdict=Verdict.MIGRATION_INDUCED,
                               confidence=0.7, rationale="x", evidence=evidence or [])]
    return f


def test_type_precision_fix_widens_to_source_scale():
    ev = [Evidence(label="code", detail="Source `c` is declared `DECIMAL(18,4)`.",
                   data={"expr": "CAST(c AS DECIMAL(18,2))", "functions": []})]
    fix = build_fix(_finding(RootCauseCategory.TYPE_PRECISION, evidence=ev))
    assert fix and fix.kind == "widen_cast"
    assert "38,4" in fix.sql and fix.confidence >= 0.8


def test_volume_missing_fix_is_a_backfill_with_keys():
    f = _finding(RootCauseCategory.VOLUME_MISSING, recon_type=ReconType.MISSING_IN_TARGET,
                 column=None, keys=("order_id",))
    fix = build_fix(f)
    assert fix.kind == "backfill" and fix.target == "load"
    assert "LEFT ANTI JOIN" in fix.sql and "s.`order_id` = t.`order_id`" in fix.sql


def test_volume_extra_fix_dedups():
    f = _finding(RootCauseCategory.VOLUME_EXTRA, recon_type=ReconType.MISSING_IN_SOURCE,
                 column=None, keys=("k1", "k2"))
    fix = build_fix(f)
    assert fix.kind == "dedup"
    assert "row_number() OVER (PARTITION BY `k1`, `k2`" in fix.sql


def test_timezone_and_string_and_nullbool_have_expressions():
    assert "to_utc_timestamp" in build_fix(_finding(RootCauseCategory.TIMEZONE)).sql
    assert "trim(" in build_fix(_finding(RootCauseCategory.STRING_FORMAT)).sql
    assert "CASE WHEN" in build_fix(_finding(RootCauseCategory.NULL_BOOLEAN)).sql


def test_transpilation_needs_a_derivation():
    assert build_fix(_finding(RootCauseCategory.TRANSPILATION)) is None
    ev = [Evidence(label="code", detail="Target derivation.",
                   data={"expr": "date_trunc('MM', d)", "functions": ["date_trunc"]})]
    fix = build_fix(_finding(RootCauseCategory.TRANSPILATION, evidence=ev))
    assert fix and "date_trunc('MM', d)" in fix.sql


def test_generate_fixes_attaches_and_skips_schema():
    col = _finding(RootCauseCategory.TIMEZONE)
    schema = _finding(RootCauseCategory.TYPE_PRECISION, recon_type=ReconType.SCHEMA, column=None)
    generate_fixes([col, schema])
    assert col.top_hypothesis.fix is not None
    assert schema.top_hypothesis.fix is None  # schema fixes are handled via the mapping


def test_fix_renders_in_notebook_and_tldr():
    f = _finding(RootCauseCategory.VOLUME_MISSING, recon_type=ReconType.MISSING_IN_TARGET,
                 column=None, keys=("order_id",))
    generate_fixes([f])
    res = RcaResult(recon_id="r", dialect="snowflake", findings=[f],
                    table_summaries=[TableSummary(source_table="cat.sch.s", target_table="cat.sch.t")])
    assert "🛠️ Suggested fixes" in build_tldr(res)
    src = "\n".join("".join(c["source"]) for c in build_notebook(res)["cells"])
    assert "Suggested fix" in src and "LEFT ANTI JOIN" in src and "spark.sql(fix_sql)" in src


# --- fix-validation gate -------------------------------------------------------------


class _FakeRunner:
    """Returns a canned row for whatever query is asked; records queries seen."""

    def __init__(self, row):
        self.row = row
        self.queries = []

    def query(self, sql):
        self.queries.append(sql)
        return [dict(self.row)]


def test_mechanical_fixes_carry_a_validation_query():
    ev = [Evidence(label="code", detail="Source `c` is declared `DECIMAL(18,4)`.",
                   data={"expr": "CAST(c AS DECIMAL(18,2))", "functions": []})]
    assert build_fix(_finding(RootCauseCategory.TYPE_PRECISION, evidence=ev)).validation_query
    assert build_fix(_finding(RootCauseCategory.TIMEZONE)).validation_query
    assert build_fix(_finding(RootCauseCategory.STRING_FORMAT)).validation_query
    miss = _finding(RootCauseCategory.VOLUME_MISSING, recon_type=ReconType.MISSING_IN_TARGET,
                    column=None, keys=("order_id",))
    assert build_fix(miss).validation_query
    extra = _finding(RootCauseCategory.VOLUME_EXTRA, recon_type=ReconType.MISSING_IN_SOURCE,
                     column=None, keys=("k1", "k2"))
    assert "count(DISTINCT" in build_fix(extra).validation_query


def test_validate_fix_marks_validated_when_query_confirms():
    f = _finding(RootCauseCategory.STRING_FORMAT)
    generate_fixes([f])
    assert validate_fix(f, _FakeRunner({"confirmed": True, "n": 42})) is True
    fix = f.top_hypothesis.fix
    assert fix.validated is True and "Validated" in fix.validation and "42" in fix.validation


def test_validate_fix_stays_suggestion_when_not_confirmed():
    f = _finding(RootCauseCategory.STRING_FORMAT)
    generate_fixes([f])
    assert validate_fix(f, _FakeRunner({"confirmed": False, "n": 10})) is False
    assert f.top_hypothesis.fix.validated is False
    assert "Not fully validated" in f.top_hypothesis.fix.validation


def test_validate_fix_is_defensive_on_query_error():
    class _Boom:
        def query(self, sql):
            raise RuntimeError("bad sql")

    f = _finding(RootCauseCategory.STRING_FORMAT)
    generate_fixes([f])
    assert validate_fix(f, _Boom()) is False
    assert "failed" in f.top_hypothesis.fix.validation.lower()


def test_validate_all_fixes_and_validated_badge_renders():
    f = _finding(RootCauseCategory.VOLUME_MISSING, recon_type=ReconType.MISSING_IN_TARGET,
                 column=None, keys=("order_id",))
    generate_fixes([f])
    validate_all_fixes([f], _FakeRunner({"confirmed": True, "n": 5}))
    res = RcaResult(recon_id="r", dialect="snowflake", findings=[f],
                    table_summaries=[TableSummary(source_table="cat.sch.s", target_table="cat.sch.t")])
    tldr = build_tldr(res)
    assert "✅" in tldr and "Valid." in tldr
    src = "\n".join("".join(c["source"]) for c in build_notebook(res)["cells"])
    assert "validated" in src.lower() and "VALIDATED by query" in src


def test_set_fix_gated_llm_proposal():
    from rca_engine.resolve import set_fix

    f = _finding(RootCauseCategory.TRANSPILATION)
    runner = _FakeRunner({"confirmed": True, "n": 7})
    ok = set_fix(
        f, runner,
        title="Rewrite mistranslated DATE_TRUNC",
        kind="fix_transpile", target="transform",
        sql="date_trunc('MONTH', `d`)",
        validation_query="SELECT true AS confirmed, 7 AS n",
    )
    assert ok is True
    fix = f.top_hypothesis.fix
    assert fix.validated is True and fix.kind == "fix_transpile"
    assert any(e.label == "fix" and e.data.get("validated") for e in f.top_hypothesis.evidence)


def test_set_fix_unvalidated_without_query():
    from rca_engine.resolve import set_fix

    f = _finding(RootCauseCategory.UNKNOWN)
    ok = set_fix(f, None, title="patch", sql="SELECT 1", kind="fix_transpile")
    assert ok is False
    assert f.top_hypothesis.fix is not None and f.top_hypothesis.fix.validated is False
