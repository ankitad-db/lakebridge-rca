"""Tests for the three post-drill-down enrichments: systemic clustering,
distribution drift, and downstream blast radius."""

from __future__ import annotations

from rca_engine.classify import classify_all
from rca_engine.cluster import build_clusters
from rca_engine.drift import run_drift
from rca_engine.lakebridge import ColumnTransform, TableMapping
from rca_engine.lineage import run_blast_radius
from rca_engine.models import (
    Evidence,
    Finding,
    Hypothesis,
    MismatchSample,
    ReconType,
    RootCauseCategory,
    TableSummary,
    Verdict,
)
from rca_engine.report import build_blast_radius, build_systemic_causes


class FakeRunner:
    """Returns a fixed row for every query (enough for the single-finding passes)."""

    def __init__(self, row: dict | list):
        self._rows = row if isinstance(row, list) else [row]

    def query(self, sql: str):  # noqa: ARG002
        return self._rows


def _num_finding(column: str, table: str, *, n: int = 5) -> Finding:
    s = [MismatchSample(keys={"id": i}, column=column, source_value="1.2345", target_value="1.23")
         for i in range(n)]
    return Finding(recon_id="r", source_table="src", target_table=table,
                   recon_type=ReconType.COLUMN_MISMATCH, column=column,
                   mismatch_count=n, total_count=100, samples=s)


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #
def test_cluster_groups_same_category_within_a_table():
    findings = classify_all([_num_finding("amount", "tgt.fact"),
                             _num_finding("price", "tgt.fact")])
    clusters = build_clusters(findings)
    assert clusters, "two same-category column findings on one table should cluster"
    c = clusters[0]
    assert c.finding_count == 2
    assert set(c.members) == {"fact.amount", "fact.price"}
    assert c.rows_impacted == 10


def test_cluster_spans_tables_when_translation_functions_match():
    # Two tables whose columns are derived by the SAME translated function set:
    # the code-correlation pass tags evidence with data.functions, so they cluster
    # across tables under one "SQL translation via ..." signature.
    def mapping_for(short):
        # classify() looks the mapping up by the short (last-segment) target name.
        return {short: TableMapping(
            target_table=short, source_table="src",
            transforms={"ts": ColumnTransform(
                target_column="ts", expr="from_utc_timestamp(ts, 'UTC')",
                functions=["from_utc_timestamp"], is_direct=False)},
        )}

    f1 = _num_finding("ts", "tgt.a")
    f2 = _num_finding("ts", "tgt.b")
    classify_all([f1], mapping=mapping_for("a"))
    classify_all([f2], mapping=mapping_for("b"))
    clusters = build_clusters([f1, f2])
    spanning = [c for c in clusters if len(c.tables) == 2]
    assert spanning, "same translated function across tables should form one cluster"
    assert "from_utc_timestamp" in spanning[0].signature


def test_cluster_ignores_singletons_and_unknowns():
    unknown = Finding(recon_id="r", source_table="src", target_table="t",
                      recon_type=ReconType.COLUMN_MISMATCH, column="c",
                      hypotheses=[Hypothesis(category=RootCauseCategory.UNKNOWN,
                                             verdict=Verdict.NEEDS_REVIEW, confidence=0.2,
                                             rationale="x")])
    assert build_clusters([unknown]) == []


def test_systemic_causes_render_when_present():
    from rca_engine.models import RcaResult

    findings = classify_all([_num_finding("amount", "tgt.fact"),
                             _num_finding("price", "tgt.fact")])
    res = RcaResult(recon_id="r", dialect="snowflake", findings=findings,
                    clusters=build_clusters(findings))
    md = build_systemic_causes(res)
    assert "Systemic root causes" in md and "fact.amount" in md


# --------------------------------------------------------------------------- #
# Distribution drift
# --------------------------------------------------------------------------- #
def _drift_row(s_nulls, t_nulls, s_ndv, t_ndv, s_avg=100.0, t_avg=99.8):
    return {
        "s_n": 1000, "s_nulls": s_nulls, "s_ndv": s_ndv, "s_avg": s_avg,
        "s_std": 12.0, "s_min": 0.0, "s_max": 500.0,
        "t_n": 1000, "t_nulls": t_nulls, "t_ndv": t_ndv, "t_avg": t_avg,
        "t_std": 12.1, "t_min": 0.0, "t_max": 500.0,
    }


def test_drift_stable_distribution_is_not_material():
    f = classify_all([_num_finding("amount", "tgt.fact")])[0]
    run_drift([f], FakeRunner(_drift_row(20, 20, 900, 900)))
    d = f.metadata["drift"]
    assert d["material"] is False
    assert any(e.label == "drift" for e in f.top_hypothesis.evidence)


def test_drift_flags_material_null_rate_jump():
    f = classify_all([_num_finding("amount", "tgt.fact")])[0]
    # null-rate 2% -> 8% is a >1pp jump => material (population changed).
    run_drift([f], FakeRunner(_drift_row(20, 80, 900, 900)))
    assert f.metadata["drift"]["material"] is True


def test_drift_flags_material_cardinality_change():
    f = classify_all([_num_finding("amount", "tgt.fact")])[0]
    run_drift([f], FakeRunner(_drift_row(20, 20, 1000, 800)))  # -20% distinct
    assert f.metadata["drift"]["material"] is True


def test_drift_is_defensive_on_query_error():
    class Boom:
        def query(self, sql):  # noqa: ARG002
            raise RuntimeError("no table")

    f = classify_all([_num_finding("amount", "tgt.fact")])[0]
    run_drift([f], Boom())  # must not raise
    assert "drift" not in f.metadata


# --------------------------------------------------------------------------- #
# Downstream blast radius
# --------------------------------------------------------------------------- #
def test_blast_radius_records_downstream_for_actionable_tables_only():
    mig = _num_finding("amount", "cat.sch.fact")
    mig.hypotheses = [Hypothesis(category=RootCauseCategory.TYPE_PRECISION,
                                 verdict=Verdict.MIGRATION_INDUCED, confidence=0.8, rationale="x")]
    benign = _num_finding("note", "cat.sch.dim")
    benign.hypotheses = [Hypothesis(category=RootCauseCategory.SEMI_STRUCTURED,
                                    verdict=Verdict.BENIGN, confidence=0.9, rationale="y")]
    summaries = [
        TableSummary(source_table="s.fact", target_table="cat.sch.fact"),
        TableSummary(source_table="s.dim", target_table="cat.sch.dim"),
    ]
    runner = FakeRunner([{"tgt": "cat.sch.report_a"}, {"tgt": "cat.sch.report_b"}])
    run_blast_radius([mig, benign], summaries, runner)

    fact = next(s for s in summaries if s.target_table == "cat.sch.fact")
    dim = next(s for s in summaries if s.target_table == "cat.sch.dim")
    assert fact.downstream_tables == ["cat.sch.report_a", "cat.sch.report_b"]
    assert dim.downstream_tables == []  # benign table is not probed
    assert any(e.label == "lineage" and "Blast radius" in e.detail
               for e in mig.top_hypothesis.evidence)


def test_blast_radius_section_renders():
    from rca_engine.models import RcaResult

    mig = _num_finding("amount", "cat.sch.fact")
    mig.hypotheses = [Hypothesis(category=RootCauseCategory.TYPE_PRECISION,
                                 verdict=Verdict.MIGRATION_INDUCED, confidence=0.8, rationale="x")]
    summ = TableSummary(source_table="s.fact", target_table="cat.sch.fact",
                        downstream_tables=["cat.sch.report_a"])
    res = RcaResult(recon_id="r", dialect="snowflake", findings=[mig], table_summaries=[summ])
    md = build_blast_radius(res)
    assert "Downstream blast radius" in md and "report_a" in md
