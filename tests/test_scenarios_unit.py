"""Deterministic scenario tests: drive every unit-testable scenario in
``migration/scenarios.yaml`` through the classifier and assert the expected
category (and verdict where the deterministic pass is conclusive).

This is the regression backbone — it exercises the RCA across every root-cause
category and edge variant without needing a workspace or a live recon run.
"""

from __future__ import annotations

import unicodedata

import pytest

from conftest import load_scenarios, make_column_finding
from rca_engine.classify import classify_all

# Scenarios that need a live drill-down/context to reach the final verdict, so the
# deterministic pass legitimately differs — we assert category only for these.
_CATEGORY_ONLY = {"S8", "S10"}

_UNIT = [s for s in load_scenarios() if s.get("example") and s.get("column")]


@pytest.mark.parametrize("sc", _UNIT, ids=[s["id"] for s in _UNIT])
def test_scenario_category_and_verdict(sc):
    f = make_column_finding(sc["column"], sc["example"]["source"], sc["example"]["target"])
    top = classify_all([f])[0].top_hypothesis
    assert top is not None, f"{sc['id']}: no hypothesis produced"
    assert top.category.value == sc["category"], (
        f"{sc['id']} {sc['column']}: category {top.category.value} != {sc['category']}"
    )
    if sc["id"] not in _CATEGORY_ONLY:
        assert top.verdict.value == sc["verdict"], (
            f"{sc['id']} {sc['column']}: verdict {top.verdict.value} != {sc['verdict']}"
        )


def test_unicode_nfc_vs_nfd_is_string_format():
    """E12: NFC vs NFD of the same text (built explicitly, since YAML can't hold NFD)."""

    src = unicodedata.normalize("NFC", "café Ürün")
    tgt = unicodedata.normalize("NFD", "café Ürün")
    assert src != tgt
    top = classify_all([make_column_finding("name_unicode", src, tgt)])[0].top_hypothesis
    assert top.category.value == "string_format"


def test_every_probe_category_is_covered_by_a_scenario():
    """Guard: the unit scenarios collectively cover the main probe categories."""

    covered = {s["category"] for s in _UNIT} | {"string_format"}
    for cat in ("type_precision", "timezone", "string_format", "null_boolean",
                "semi_structured", "transpilation", "env_config", "upstream_drift"):
        assert cat in covered, f"no unit scenario covers {cat}"
