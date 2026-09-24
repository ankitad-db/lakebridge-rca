"""Tests for the job-level source-column trace (rca_engine/mismatch_trace.py).

The trace logic is pure over SQL strings, so it exercises fully offline: a small
multi-hop ETL fixture (temp view -> aggregate -> INSERT INTO target) is parsed and a
mismatching target column is walked back to its true source columns, and a reproduction
query is assembled. Job discovery and the end-to-end pass are tested with fake runners /
a monkeypatched export so no workspace is needed."""

from __future__ import annotations

import pytest

pytest.importorskip("sqlglot")  # the pass is a no-op without sqlglot

from rca_engine import mismatch_trace as mt  # noqa: E402
from rca_engine.models import (  # noqa: E402
    Finding,
    Hypothesis,
    MismatchSample,
    ReconType,
    RootCauseCategory,
    Verdict,
)

# net_revenue is computed from THREE source columns and renamed at each hop — a filter
# reusing the target column name against a source table would be meaningless.
ETL_SQL = """
CREATE OR REPLACE TEMPORARY VIEW enr_lines AS
SELECT s.order_id AS order_id,
       s.qty * s.price * (1 - s.disc / 10.0) AS net_revenue
FROM prod_edw.raw_sales s;

CREATE OR REPLACE TEMPORARY VIEW final_output AS
SELECT order_id, SUM(net_revenue) AS net_revenue
FROM enr_lines
GROUP BY order_id;

INSERT INTO cat.sch.fact_orders
SELECT * FROM final_output;
"""


class FakeRunner:
    """Returns canned rows for any query; raises if constructed with an exception."""

    def __init__(self, rows=None, exc: Exception | None = None):
        self._rows = rows or []
        self._exc = exc

    def query(self, sql: str):
        if self._exc is not None:
            raise self._exc
        return self._rows


def _model():
    return mt.build_source_map([("task", "/nb", ETL_SQL)])


def _col_finding(table="cat.sch.fact_orders", column="net_revenue", verdict=Verdict.MIGRATION_INDUCED):
    f = Finding(
        recon_id="r",
        source_table="snow.raw_sales",
        target_table=table,
        recon_type=ReconType.COLUMN_MISMATCH,
        column=column,
        mismatch_count=3,
        total_count=100,
        samples=[MismatchSample(keys={"order_id": 123}, column=column, source_value="9.9", target_value="9.8")],
    )
    f.hypotheses = [
        Hypothesis(
            category=RootCauseCategory.TRANSPILATION,
            verdict=verdict,
            confidence=0.9,
            rationale="test",
        )
    ]
    return f


# --------------------------------------------------------------------------- #
# source-map + column trace
# --------------------------------------------------------------------------- #
def test_source_map_registers_temps_and_insert_root():
    m = _model()
    assert "enr_lines" in m.sources
    assert "final_output" in m.sources
    # INSERT INTO target is a root, registered at every suffix depth.
    assert m.root_for("fact_orders") is not None
    assert "cat.sch.fact_orders" in m.insert_targets
    # creation order preserved (each CTE later references only earlier ones).
    assert m.create_order.index("enr_lines") < m.create_order.index("final_output")


def test_trace_column_reaches_true_source_columns():
    m = _model()
    root_sql = mt._unwrap_star(m.root_for("fact_orders"), m.sources)
    chain, leaves = mt.trace_column("net_revenue", root_sql, m)

    # Leaves resolve to the REAL source table's operand columns, not a same-named column.
    true_sources = [(lc.split(".")[-1].lower(), tb) for lc, tb, ok in leaves if ok]
    assert true_sources, "expected at least one true external source column"
    assert all(tb and tb.endswith("raw_sales") for _, tb in true_sources)
    src_cols = {c for c, _ in true_sources}
    assert {"qty", "price", "disc"} & src_cols, f"expected operand cols, got {src_cols}"
    # The transform chain captured the aggregate/arithmetic on the way down.
    assert any("SUM" in ln or "*" in ln for ln in chain)


def test_reproduction_query_inlines_chain_in_creation_order():
    m = _model()
    q = mt.build_reproduction_query("final_output", "order_id = 123", m)
    assert q.startswith("WITH")
    assert "enr_lines AS" in q and "final_output AS" in q
    assert q.index("enr_lines AS") < q.index("final_output AS")  # dependency order
    assert "SELECT * FROM final_output" in q
    assert "WHERE order_id = 123" in q


def test_substitute_roundtrips_catalog_placeholder():
    assert mt.unsubstitute(mt.substitute("FROM ${edw}.t", "")) == "FROM ${edw}.t"
    assert mt.substitute("FROM ${edw}.t", "prod") == "FROM prod.t"


# --------------------------------------------------------------------------- #
# job discovery via system tables
# --------------------------------------------------------------------------- #
def test_resolve_job_returns_most_frequent_entity_id():
    runner = FakeRunner([{"job_id": "42", "n": 7}, {"job_id": "9", "n": 1}])
    assert mt.resolve_job_for_table(runner, "cat.sch.fact_orders") == "42"


def test_resolve_job_returns_none_when_no_job_or_error():
    assert mt.resolve_job_for_table(FakeRunner([]), "cat.sch.fact_orders") is None
    assert mt.resolve_job_for_table(FakeRunner(exc=RuntimeError("denied")), "cat.sch.x") is None


# --------------------------------------------------------------------------- #
# the pass (end to end, no workspace)
# --------------------------------------------------------------------------- #
def test_run_mismatch_trace_attaches_source_trace(monkeypatch):
    monkeypatch.setattr(mt, "export_job_sql", lambda jid, ws: [("task", "/nb", ETL_SQL)])
    findings = [_col_finding()]
    mt.run_mismatch_trace(findings, FakeRunner([]), ws=object(), job_id="42")

    ev = findings[0].top_hypothesis.evidence
    trace = [e for e in ev if e.label == "source_trace"]
    assert len(trace) == 1
    assert trace[0].data["job_id"] == "42"
    assert trace[0].data["true_source_columns"]
    assert trace[0].query and trace[0].query.startswith("WITH")
    assert "WHERE order_id = 123" in trace[0].query


def test_pass_is_noop_when_no_job_found(monkeypatch):
    called = {"export": False}

    def _export(jid, ws):
        called["export"] = True
        return []

    monkeypatch.setattr(mt, "export_job_sql", _export)
    findings = [_col_finding()]
    # FakeRunner([]) -> resolve_job returns None, and no --job-id -> skip, never export.
    mt.run_mismatch_trace(findings, FakeRunner([]), ws=object(), job_id=None)
    assert not called["export"]
    assert not any(e.label == "source_trace" for e in findings[0].top_hypothesis.evidence)


def test_pass_skips_benign_and_non_column_findings(monkeypatch):
    monkeypatch.setattr(mt, "export_job_sql", lambda jid, ws: [("task", "/nb", ETL_SQL)])
    benign = _col_finding(verdict=Verdict.BENIGN)
    volume = Finding(
        recon_id="r", source_table="s", target_table="cat.sch.fact_orders",
        recon_type=ReconType.MISSING_IN_TARGET,
    )
    volume.hypotheses = [
        Hypothesis(category=RootCauseCategory.VOLUME_MISSING, verdict=Verdict.MIGRATION_INDUCED,
                   confidence=0.8, rationale="t")
    ]
    findings = [benign, volume]
    mt.run_mismatch_trace(findings, FakeRunner([]), ws=object(), job_id="42")
    for f in findings:
        assert not any(e.label == "source_trace" for e in f.top_hypothesis.evidence)
