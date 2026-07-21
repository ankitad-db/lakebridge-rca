"""Tests for report/notebook generation from a classified result."""

from __future__ import annotations

from rca_engine.classify import classify_all
from rca_engine.models import (
    Finding,
    MismatchSample,
    RcaResult,
    ReconType,
    TableSummary,
)
from rca_engine.report import build_conclusion, build_notebook, build_tldr, to_dict


def _sample_result() -> RcaResult:
    s = [MismatchSample(keys={"id": i}, column="amount", source_value="1.2345", target_value="1.23")
         for i in range(5)]
    f = Finding(recon_id="r1", source_table="src.fact", target_table="tgt.fact",
                recon_type=ReconType.COLUMN_MISMATCH, column="amount",
                mismatch_count=5, total_count=100, samples=s)
    findings = classify_all([f])
    summ = [TableSummary(source_table="src.fact", target_table="tgt.fact",
                         source_count=100, target_count=100, absolute_mismatch=5,
                         mismatch_columns=["amount"], join_keys=["id"])]
    return RcaResult(recon_id="r1", dialect="snowflake", findings=findings, table_summaries=summ)


def test_build_tldr_has_core_sections():
    tldr = build_tldr(_sample_result())
    assert "RCA Summary" in tldr
    assert "Match rates" in tldr


def test_build_notebook_structure():
    nb = build_notebook(_sample_result())
    assert nb["nbformat"] == 4
    assert len(nb["cells"]) > 3
    assert all("cell_type" in c for c in nb["cells"])


def test_notebook_has_validation_widgets():
    nb = build_notebook(_sample_result())
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "dbutils.widgets" in src
    assert "validate_rows" in src


def test_conclusion_groups_by_owner():
    assert "migration engineer" in build_conclusion(_sample_result()).lower()


def test_to_dict_roundtrip_keys():
    d = to_dict(_sample_result())
    assert d["recon_id"] == "r1"
    assert d["findings"] and d["findings"][0]["column"] == "amount"


def test_verdict_counts():
    counts = _sample_result().verdict_counts()
    assert counts["migration_induced"] >= 1
