"""Tests for the non-column classification paths (volume, schema, fallback) and
the code-correlation pass that uses Lakebridge mappings."""

from __future__ import annotations

from rca_engine.classify import classify_all
from rca_engine.lakebridge import ColumnTransform, TableMapping
from rca_engine.models import Finding, MismatchSample, ReconType, RootCauseCategory, Verdict


def _finding(recon_type, table="tgt", column=None, mismatch=10, total=100, samples=None):
    return Finding(recon_id="t", source_table="src", target_table=table,
                   recon_type=recon_type, column=column, mismatch_count=mismatch,
                   total_count=total, samples=samples or [])


def test_missing_in_target_is_volume_missing():
    top = classify_all([_finding(ReconType.MISSING_IN_TARGET)])[0].top_hypothesis
    assert top.category == RootCauseCategory.VOLUME_MISSING
    assert top.verdict == Verdict.MIGRATION_INDUCED


def test_missing_in_source_is_volume_extra():
    top = classify_all([_finding(ReconType.MISSING_IN_SOURCE)])[0].top_hypothesis
    assert top.category == RootCauseCategory.VOLUME_EXTRA


def test_schema_is_type_precision():
    top = classify_all([_finding(ReconType.SCHEMA)])[0].top_hypothesis
    assert top.category == RootCauseCategory.TYPE_PRECISION


def test_unknown_when_no_probe_fires():
    # Two arbitrary unequal strings that no probe explains.
    s = [MismatchSample(keys={"id": 1}, column="c", source_value="alpha", target_value="omega")]
    top = classify_all([_finding(ReconType.COLUMN_MISMATCH, column="c", samples=s)])[0].top_hypothesis
    assert top.category == RootCauseCategory.UNKNOWN
    assert top.verdict == Verdict.NEEDS_REVIEW


def test_code_correlation_direct_passthrough_downgrades_transpilation():
    s = [MismatchSample(keys={"id": 1}, column="c", source_value="alpha", target_value="omega")]
    f = _finding(ReconType.COLUMN_MISMATCH, column="c", samples=s)
    mapping = {"tgt": TableMapping(
        target_table="tgt",
        transforms={"c": ColumnTransform(target_column="c", expr="c", is_direct=True)},
    )}
    top = classify_all([f], mapping=mapping)[0].top_hypothesis
    assert any(e.label == "code" for e in top.evidence)


def test_code_correlation_generated_column_flags_needs_review():
    # A column with a provenance (source-null) verdict that the code shows is generated.
    s = [MismatchSample(keys={"id": i}, column="loyalty_tier", source_value=None, target_value="Gold")
         for i in range(5)]
    f = _finding(ReconType.COLUMN_MISMATCH, column="loyalty_tier", samples=s)
    mapping = {"tgt": TableMapping(
        target_table="tgt",
        transforms={"loyalty_tier": ColumnTransform(
            target_column="loyalty_tier",
            expr="element_at(array('Bronze','Silver','Gold'), x)", is_direct=False)},
    )}
    top = classify_all([f], mapping=mapping)[0].top_hypothesis
    assert f.metadata.get("code_generated") is True
    assert top.verdict == Verdict.NEEDS_REVIEW


def test_code_correlation_source_type_scale_loss():
    s = [MismatchSample(keys={"id": i}, column="amount", source_value="1.2345", target_value="1.23")
         for i in range(5)]
    f = _finding(ReconType.COLUMN_MISMATCH, column="amount", samples=s)
    mapping = {"tgt": TableMapping(
        target_table="tgt", source_table="src",
        source_types={"amount": "DECIMAL(18,4)"},
        transforms={"amount": ColumnTransform(
            target_column="amount", expr="CAST(amount AS DECIMAL(18,2))", is_direct=False)},
    )}
    top = classify_all([f], mapping=mapping)[0].top_hypothesis
    assert any("scale" in e.detail.lower() and e.label == "code" for e in top.evidence)
