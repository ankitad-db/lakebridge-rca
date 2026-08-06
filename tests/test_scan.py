"""Tests for scan scoping — flagged-key binding and partition/date windowing."""

from __future__ import annotations

from rca_engine.drift import _drift_query
from rca_engine.drilldown import run_drilldown
from rca_engine.fixgen import generate_fixes
from rca_engine.models import (
    Finding,
    Hypothesis,
    MismatchSample,
    ReconType,
    RootCauseCategory,
    Verdict,
)
from rca_engine.scan import ScanScope, key_in_clause, partition_clause


def _finding(category, *, column="c", recon_type=ReconType.COLUMN_MISMATCH,
             keys=(("id", 1), ("id", 2), ("id", 3)), table="cat.sch.t",
             mismatch=9999, evidence=None) -> Finding:
    samples = [MismatchSample(keys={k: v}, column=column, source_value="x", target_value="y")
               for k, v in keys]
    f = Finding(recon_id="r", source_table="cat.sch.s", target_table=table,
                recon_type=recon_type, column=column, mismatch_count=mismatch, total_count=100000,
                samples=samples)
    f.hypotheses = [Hypothesis(category=category, verdict=Verdict.MIGRATION_INDUCED,
                               confidence=0.7, rationale="x", evidence=evidence or [])]
    return f


class _Runner:
    def __init__(self):
        self.queries = []

    def query(self, sql):
        self.queries.append(sql)
        # Return a confirming row (numbers keep drill-down/fix logic happy).
        return [{"confirmed": True, "n": 3, "distinct_offsets": 1, "offset_hours": 5.0,
                 "cosmetic": 3, "null_involved": 1, "avg_abs_diff": 0.01, "max_abs_diff": 0.02,
                 "eq_at_2dp": 3, "extra": 0, "src_total": 3, "src_nulls": 0}]


# --- clause builders ----------------------------------------------------------------


def test_key_in_clause_single_and_composite():
    scope = ScanScope(mode="scoped")
    f = _finding(RootCauseCategory.STRING_FORMAT)
    assert key_in_clause(f, scope, "s") == "s.`id` IN (1, 2, 3)"

    comp = Finding(recon_id="r", source_table="s", target_table="t",
                   recon_type=ReconType.COLUMN_MISMATCH, column="c", mismatch_count=1,
                   total_count=1, samples=[MismatchSample(keys={"a": 1, "b": "x"}, column="c")])
    clause = key_in_clause(comp, scope, "s")
    assert clause == "((s.`a` = 1 AND s.`b` = 'x'))"


def test_key_in_clause_empty_when_full_or_no_keys():
    assert key_in_clause(_finding(RootCauseCategory.STRING_FORMAT), ScanScope(mode="full"), "s") == ""
    assert key_in_clause(_finding(RootCauseCategory.STRING_FORMAT), None, "s") == ""


def test_key_in_clause_caps_at_max_keys():
    scope = ScanScope(mode="scoped", max_keys=2)
    f = _finding(RootCauseCategory.STRING_FORMAT, keys=(("id", 1), ("id", 2), ("id", 3)))
    assert key_in_clause(f, scope, "s") == "s.`id` IN (1, 2)"


def test_partition_clause():
    scope = ScanScope(mode="scoped", partition_column="load_dt",
                      date_start="2024-01-01", date_end="2024-01-31")
    assert partition_clause(scope, "s") == "s.`load_dt` BETWEEN '2024-01-01' AND '2024-01-31'"
    assert partition_clause(scope, "") == "`load_dt` BETWEEN '2024-01-01' AND '2024-01-31'"
    assert partition_clause(ScanScope(mode="scoped"), "s") == ""  # no window configured


def test_lit_escapes_quotes():
    from rca_engine.scan import _lit
    assert _lit("O'Brien") == "'O''Brien'"
    assert _lit(None) == "NULL"
    assert _lit(True) == "true"


# --- integration: scoped queries ----------------------------------------------------


def test_drilldown_scopes_to_keys_and_keeps_recon_count():
    f = _finding(RootCauseCategory.STRING_FORMAT, mismatch=9999)
    runner = _Runner()
    run_drilldown([f], runner, ScanScope(mode="scoped"))
    sql = runner.queries[0]
    assert "IN (1, 2, 3)" in sql
    # key-scoped ⇒ the recon-derived total (9999) is NOT overwritten by the sample n (3)
    assert f.mismatch_count == 9999
    ev = f.top_hypothesis.evidence[0]
    assert "[scoped to flagged keys]" in ev.detail


def test_drilldown_full_mode_overwrites_count_and_no_in_clause():
    f = _finding(RootCauseCategory.STRING_FORMAT, mismatch=9999)
    runner = _Runner()
    run_drilldown([f], runner, ScanScope(mode="full"))
    sql = runner.queries[0]
    assert " IN (" not in sql
    assert f.mismatch_count == 3  # full confirm ⇒ exact n from the query


def test_drift_query_windows_when_partition_set():
    scope = ScanScope(mode="scoped", partition_column="load_dt",
                      date_start="2024-01-01", date_end="2024-01-31")
    q = _drift_query("cat.sch.s", "cat.sch.t", "c", scope)
    assert q.count("BETWEEN '2024-01-01' AND '2024-01-31'") >= 2  # both source & target blocks
    q_full = _drift_query("cat.sch.s", "cat.sch.t", "c", ScanScope(mode="full"))
    assert "BETWEEN" not in q_full


def test_fix_validation_query_is_scoped_to_keys():
    f = _finding(RootCauseCategory.STRING_FORMAT)
    generate_fixes([f], ScanScope(mode="scoped"))
    assert "IN (1, 2, 3)" in f.top_hypothesis.fix.validation_query
