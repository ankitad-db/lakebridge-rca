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
from rca_engine.report import (
    build_conclusion,
    build_index_notebook,
    build_notebook,
    build_tldr,
    to_dict,
    write_rca_bundle,
)


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


def _multi_table_result() -> RcaResult:
    base = _sample_result()
    f2 = Finding(recon_id="r1", source_table="src.dim", target_table="tgt.dim",
                 recon_type=ReconType.COLUMN_MISMATCH, column="name",
                 mismatch_count=2, total_count=50,
                 samples=[MismatchSample(keys={"id": 1}, column="name",
                                         source_value="A", target_value="a")])
    findings = base.findings + classify_all([f2])
    summ = base.table_summaries + [
        TableSummary(source_table="src.dim", target_table="tgt.dim",
                     source_count=50, target_count=50, absolute_mismatch=2,
                     mismatch_columns=["name"], join_keys=["id"]),
        TableSummary(source_table="src.clean", target_table="tgt.clean",
                     source_count=10, target_count=10),
    ]
    return RcaResult(recon_id="r1", dialect="snowflake", findings=findings, table_summaries=summ)


def test_write_rca_bundle_folder_layout(tmp_path):
    import os

    res = _multi_table_result()
    folder = write_rca_bundle(res, str(tmp_path), "r1")
    assert folder.endswith("rca_r1")
    files = set(os.listdir(folder))
    # per-recon folder: index + summary + findings JSON + one notebook per table
    assert "00_index.ipynb" in files
    assert "SUMMARY.md" in files
    assert "rca_r1.json" in files
    assert {"fact.ipynb", "dim.ipynb", "clean.ipynb"} <= files
    # combined book only when requested
    assert "rca_r1_all.ipynb" not in files


def test_summary_md_is_shareable_markdown(tmp_path):
    import os

    from rca_engine.report import build_summary_md

    md = build_summary_md(_multi_table_result())
    assert "# 🧭 RCA Summary" in md and "Conclusion" in md
    folder = write_rca_bundle(_multi_table_result(), str(tmp_path), "r9")
    with open(os.path.join(folder, "SUMMARY.md")) as f:
        assert "RCA Summary" in f.read()


def test_write_rca_bundle_combined_and_single_table(tmp_path):
    import os

    res = _multi_table_result()
    folder = write_rca_bundle(res, str(tmp_path), "r2", combined=True)
    assert "rca_r2_all.ipynb" in set(os.listdir(folder))

    single = write_rca_bundle(_sample_result(), str(tmp_path), "r3")
    files = set(os.listdir(single))
    # single-table run: no index page, just the one table + json
    assert "00_index.ipynb" not in files
    assert "fact.ipynb" in files and "rca_r3.json" in files


def test_index_notebook_lists_all_tables():
    res = _multi_table_result()
    nb = build_index_notebook(res, {"tgt.fact": "rca_r1_tgt.fact.ipynb"})
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "tgt.fact" in src and "tgt.dim" in src and "tgt.clean" in src


def test_per_table_notebook_only_has_that_tables_findings():
    from rca_engine.report import _subresult

    res = _multi_table_result()
    sub = _subresult(res, "tgt.dim")
    assert {f.target_table for f in sub.findings} == {"tgt.dim"}
    assert {s.target_table for s in sub.table_summaries} == {"tgt.dim"}
