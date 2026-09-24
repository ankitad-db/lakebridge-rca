"""Aggregate-reconcile RCA: group-key divergence vs value drift classification."""
from rca_engine.aggregate_rca import _confirm_query, run_aggregate_rca
from rca_engine.models import ReconType, Verdict


class FakeRunner:
    """Returns canned aggregate_metrics rows, then a 'confirmed' row for any WITH/SELECT."""

    def __init__(self, rows):
        self._rows = rows

    def query(self, sql):
        if "aggregate_metrics" in sql:
            return self._rows
        return [{"n": 2, "confirmed": True}]


def _row(**kw):
    base = {"src": "c.s.fact_sales", "tgt": "c.t.fact_sales", "agg_type": "sum",
            "agg_col": "net_revenue", "grp": "is_active",
            "mismatch": 0, "mis_src": 0, "mis_tgt": 0}
    base.update(kw)
    return base


def test_group_key_divergence_is_flagged_migration_induced():
    findings = run_aggregate_rca(FakeRunner([_row(mis_src=2, mis_tgt=2)]), "rid", "c", "reconcile")
    assert len(findings) == 1
    f = findings[0]
    assert f.recon_type == ReconType.AGGREGATE
    top = f.top_hypothesis
    assert top.verdict == Verdict.MIGRATION_INDUCED
    assert "GROUP BY" in top.rationale
    # a confirming query is attached
    assert any(e.label == "drilldown" and e.query for e in top.evidence)


def test_value_drift_is_flagged():
    findings = run_aggregate_rca(FakeRunner([_row(mismatch=3)]), "rid", "c", "reconcile")
    assert len(findings) == 1
    assert "differs for 3 matching group" in findings[0].top_hypothesis.rationale


def test_clean_rule_produces_no_finding():
    assert run_aggregate_rca(FakeRunner([_row()]), "rid", "c", "reconcile") == []


def test_confirm_query_groups_and_compares():
    q = _confirm_query("c.s.fact_sales", "c.t.fact_sales", "sum", "net_revenue", "is_active")
    assert "GROUP BY" in q and "FULL OUTER JOIN" in q and "confirmed" in q
