"""Core data model for the RCA engine.

These types are independent of any recon-output schema or execution backend so
they can be shared by the ingester, probes, classifier, report generator, and a
future MCP wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ReconType(str, Enum):
    """The kind of difference Lakebridge reconcile emits."""

    SCHEMA = "schema"
    MISSING_IN_TARGET = "missing_in_target"
    MISSING_IN_SOURCE = "missing_in_source"
    COLUMN_MISMATCH = "column_mismatch"


class RootCauseCategory(str, Enum):
    """Technical category of a mismatch (what mechanism produced it)."""

    TYPE_PRECISION = "type_precision"          # numeric scale/precision, DOUBLE vs DECIMAL
    TIMEZONE = "timezone"                      # TIMESTAMP_LTZ vs UTC, offset shift
    SEMI_STRUCTURED = "semi_structured"        # VARIANT/JSON key ordering, serialization
    STRING_FORMAT = "string_format"            # case, whitespace, collation, encoding
    TRANSPILATION = "transpilation"            # SQL semantic diff (DATE_TRUNC, ROUND, etc.)
    VOLUME_MISSING = "volume_missing"          # rows missing in target
    VOLUME_EXTRA = "volume_extra"              # duplicate / fan-out rows
    UPSTREAM_DRIFT = "upstream_drift"          # snapshot skew, late data
    NULL_BOOLEAN = "null_boolean"              # NULL-vs-empty, 'Y'/'N' -> boolean
    ENV_CONFIG = "env_config"                  # session tz, ANSI mode, collation config
    RECON_CONFIG = "recon_config"              # tolerance/keys/transform in recon itself
    UNKNOWN = "unknown"


class Verdict(str, Enum):
    """Top-level determination, separate from the technical category.

    Not every mismatch is a migration defect. This is the field a human acts on.
    """

    MIGRATION_INDUCED = "migration_induced"    # fix in the migration
    GENUINE_DATA = "genuine_data"              # real source/upstream difference; route to data owner
    BENIGN = "benign"                          # formatting-only / within tolerance; no action
    NEEDS_REVIEW = "needs_review"              # evidence inconclusive


@dataclass
class MismatchSample:
    """A single sampled row-level difference from the recon details."""

    keys: dict[str, Any]
    column: Optional[str] = None
    source_value: Any = None
    target_value: Any = None


@dataclass
class Evidence:
    """A piece of supporting evidence gathered by a probe or a live query."""

    label: str
    detail: str
    query: Optional[str] = None
    data: Any = None


@dataclass
class Hypothesis:
    """A candidate explanation for a finding, with a confidence in [0, 1]."""

    category: RootCauseCategory
    verdict: Verdict
    confidence: float
    rationale: str
    remediation: str = ""
    recommended_owner: str = ""
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Finding:
    """A normalized mismatch for one (table, [column]) from a recon run."""

    recon_id: str
    source_table: str
    target_table: str
    recon_type: ReconType
    column: Optional[str] = None
    mismatch_count: int = 0
    total_count: int = 0
    samples: list[MismatchSample] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Populated by the classifier.
    hypotheses: list[Hypothesis] = field(default_factory=list)

    @property
    def top_hypothesis(self) -> Optional[Hypothesis]:
        if not self.hypotheses:
            return None
        return max(self.hypotheses, key=lambda h: h.confidence)


@dataclass
class RcaResult:
    """The full RCA output for a recon run."""

    recon_id: str
    dialect: str
    findings: list[Finding] = field(default_factory=list)

    def verdict_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {v.value: 0 for v in Verdict}
        for f in self.findings:
            top = f.top_hypothesis
            if top is not None:
                counts[top.verdict.value] += 1
        return counts
