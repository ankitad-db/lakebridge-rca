"""Load and query the per-dialect knowledge base (YAML-backed)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_KB_DIR = Path(__file__).parent


@dataclass
class KnowledgeBase:
    """Curated catalog of source-dialect vs Databricks semantic differences."""

    dialect: str
    type_mappings: list[dict[str, Any]] = field(default_factory=list)
    function_diffs: list[dict[str, Any]] = field(default_factory=list)
    remediation: dict[str, str] = field(default_factory=dict)

    def remediation_for(self, category: str) -> str:
        return self.remediation.get(category, "")

    def risky_functions(self) -> list[str]:
        return [f["function"] for f in self.function_diffs if "function" in f]


def load_kb(dialect: str = "snowflake") -> KnowledgeBase:
    """Load the knowledge base for a dialect. Falls back to an empty KB."""

    path = _KB_DIR / f"{dialect}.yaml"
    if not path.exists():
        return KnowledgeBase(dialect=dialect)
    data = yaml.safe_load(path.read_text()) or {}
    return KnowledgeBase(
        dialect=data.get("dialect", dialect),
        type_mappings=data.get("type_mappings", []),
        function_diffs=data.get("function_diffs", []),
        remediation=data.get("remediation", {}),
    )
