"""Correlate a mismatched column with risky constructs in the translated SQL.

Given the transformation SQL that produced a target column, flag functions that
have known source<->Databricks semantic differences (from the knowledge base).
This raises confidence that a column mismatch is transpilation-induced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rca_engine.knowledge import KnowledgeBase


@dataclass
class CodeCorrelation:
    matched_functions: list[str]
    detail: str


def correlate(sql: str | None, kb: KnowledgeBase) -> CodeCorrelation:
    if not sql:
        return CodeCorrelation([], "No transformation SQL provided.")
    lowered = sql.lower()
    hits: list[str] = []
    for diff in kb.function_diffs:
        fn = str(diff.get("function", "")).split("(")[0].strip().lower()
        if fn and re.search(rf"\b{re.escape(fn)}\b", lowered):
            hits.append(diff.get("function", fn))
    if hits:
        return CodeCorrelation(
            matched_functions=hits,
            detail=f"Transformation uses functions with known semantic differences: {hits}. "
            f"A transpilation issue is a strong candidate.",
        )
    return CodeCorrelation([], "No known-risky functions found in the transformation SQL.")
