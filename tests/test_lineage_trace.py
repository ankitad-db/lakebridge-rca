"""Tests for the depth-agnostic upstream lineage trace-back.

A ``LineageRunner`` answers ``system.access.column_lineage`` / ``table_lineage`` queries
from an in-memory graph, so we can assert the walk reaches the root regardless of how many
layers there are, breaks cycles, and honors the hop budget."""

from __future__ import annotations

import re

from rca_engine.classify import classify_all
from rca_engine.lineage import run_lineage, trace_upstream
from rca_engine.models import Finding, MismatchSample, ReconType


class LineageRunner:
    """Serves column/table lineage from a graph of ``child -> [parents]`` edges.

    ``col_edges``: {(table, column): [(src_table, src_col), ...]}
    ``tbl_edges``: {table: [src_table, ...]}
    """

    def __init__(self, col_edges: dict | None = None, tbl_edges: dict | None = None):
        self.col_edges = col_edges or {}
        self.tbl_edges = tbl_edges or {}

    def query(self, sql: str):
        low = sql.lower()
        if "column_lineage" in low:
            t = re.search(r"lower\(target_table_full_name\)\s*=\s*lower\('([^']+)'\)", sql)
            c = re.search(r"lower\(target_column_name\)\s*=\s*lower\('([^']+)'\)", sql)
            if not t:
                return []
            table = t.group(1).lower()
            if c:  # per-column parents (recursive walk)
                col = c.group(1).lower()
                return [
                    {"src_tbl": st, "src_col": sc}
                    for (st, sc) in self.col_edges.get((table, col), [])
                ]
            # grouped one-hop fetch_lineage form
            rows = []
            for (tbl, col), parents in self.col_edges.items():
                if tbl == table:
                    for (st, sc) in parents:
                        rows.append({"src_tbl": st, "src_col": sc, "tgt_col": col})
            return rows
        if "table_lineage" in low:
            t = re.search(r"lower\(target_table_full_name\)\s*=\s*lower\('([^']+)'\)", sql)
            if not t:
                return []
            table = t.group(1).lower()
            return [{"src_tbl": st} for st in self.tbl_edges.get(table, [])]
        return []


def _col_finding(table: str, column: str) -> Finding:
    s = [MismatchSample(keys={"id": i}, column=column, source_value="1.2345", target_value="1.23")
         for i in range(5)]
    return Finding(recon_id="r", source_table="snow.src", target_table=table,
                   recon_type=ReconType.COLUMN_MISMATCH, column=column,
                   mismatch_count=5, total_count=100, samples=s)


def test_column_trace_reaches_root_over_many_hops():
    # target.amount <- l3.amt <- l2.amt <- l1.amount (root). 3 hops, arbitrary depth.
    runner = LineageRunner(col_edges={
        ("cat.sch.target", "amount"): [("cat.sch.l3", "amt")],
        ("cat.sch.l3", "amt"): [("cat.sch.l2", "amt")],
        ("cat.sch.l2", "amt"): [("cat.sch.l1", "amount")],
        ("cat.sch.l1", "amount"): [],  # root
    })
    chain = trace_upstream(runner, "cat.sch.target", "amount")
    assert chain.max_depth == 3
    assert chain.root_tables() == ["cat.sch.l1"]
    assert not chain.truncated
    path = chain.paths[0]
    assert [n.table for n in path] == ["cat.sch.target", "cat.sch.l3", "cat.sch.l2", "cat.sch.l1"]


def test_trace_is_depth_agnostic_beyond_three_layers():
    # 5-layer chain — proves it isn't hard-coded to 3.
    edges = {(f"t.l{i}", "v"): [(f"t.l{i+1}", "v")] for i in range(5)}
    edges[("t.l5", "v")] = []
    edges[("t.target", "v")] = [("t.l0", "v")]
    chain = trace_upstream(LineageRunner(col_edges=edges), "t.target", "v")
    assert chain.max_depth == 6
    assert chain.root_tables() == ["t.l5"]


def test_hop_budget_truncates_without_crashing():
    edges = {(f"t.l{i}", "v"): [(f"t.l{i+1}", "v")] for i in range(20)}
    chain = trace_upstream(LineageRunner(col_edges=edges), "t.l0", "v", max_hops=3)
    assert chain.truncated
    assert chain.max_depth == 3


def test_cycle_is_broken():
    # a -> b -> a (cycle) must not loop forever.
    edges = {("t.a", "v"): [("t.b", "v")], ("t.b", "v"): [("t.a", "v")]}
    chain = trace_upstream(LineageRunner(col_edges=edges), "t.a", "v")
    assert chain.paths  # terminates
    for p in chain.paths:
        keys = [(n.table, n.column) for n in p]
        assert len(keys) == len(set(keys)), "no node repeats on a path"


def test_run_lineage_attaches_traceback_evidence():
    runner = LineageRunner(col_edges={
        ("cat.sch.target", "amount"): [("cat.sch.stg", "amt")],
        ("cat.sch.stg", "amt"): [("cat.sch.raw", "amount")],
        ("cat.sch.raw", "amount"): [],
    })
    findings = classify_all([_col_finding("cat.sch.target", "amount")])
    run_lineage(findings, runner)
    ev = findings[0].top_hypothesis.evidence
    assert any(e.label == "lineage" and "trace-back" in e.detail.lower() for e in ev)
    trace = next(e for e in ev if "trace-back" in e.detail.lower())
    assert trace.data["roots"] == ["cat.sch.raw"]
    assert trace.data["max_depth"] == 2


def test_table_level_trace_for_volume_finding():
    runner = LineageRunner(tbl_edges={
        "cat.sch.target": ["cat.sch.stg"],
        "cat.sch.stg": ["cat.sch.raw"],
        "cat.sch.raw": [],
    })
    chain = trace_upstream(runner, "cat.sch.target", None)
    assert chain.max_depth == 2
    assert chain.root_tables() == ["cat.sch.raw"]
