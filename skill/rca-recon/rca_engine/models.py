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
    AGGREGATE = "aggregate"                     # aggregates-reconcile per-rule (SUM/AVG/COUNT/...)


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
class Fix:
    """A concrete, runnable remediation for a finding — the corrected transform
    expression, a recon-config change, or a load/back-fill statement.

    It is a **suggestion**: the engine never applies it. The RCA notebook surfaces it
    in a cell the reviewer inspects and runs manually. ``target`` says what it changes:
    ``transform`` (migrated SQL), ``recon_config`` (tolerance/mapping), or ``load``
    (back-fill / de-dup / watermark).
    """

    title: str
    kind: str
    sql: str
    target: str = "transform"
    rationale: str = ""
    confidence: float = 0.0
    # Fix-validation gate: an aggregate query that checks the gap this fix addresses is
    # the *entire* difference (so applying the fix would close it). ``validated`` is set
    # once the query runs; ``validation`` is the human-readable result. Empty query ⇒ the
    # fix stays an unvalidated suggestion.
    validated: bool = False
    validation: str = ""
    validation_query: str = ""


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
    # A concrete, runnable fix generated for this hypothesis (see rca_engine/fixgen.py).
    fix: Optional["Fix"] = None


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
class TableSummary:
    """Per-table-pair reconciliation totals (from Lakebridge recon metrics).

    Captured for *every* reconciled table pair, including clean ones, so the report
    can show an overall row-level and column-level match rate — not just the issues.
    """

    source_table: str
    target_table: str
    source_count: int = 0
    target_count: int = 0
    missing_in_source: int = 0   # rows in target but not source (extra in target)
    missing_in_target: int = 0   # rows in source but not target (missing in target)
    absolute_mismatch: int = 0   # common rows that differ on >= 1 column
    mismatch_columns: list[str] = field(default_factory=list)
    schema_ok: bool = True
    join_keys: list[str] = field(default_factory=list)
    date_column: Optional[str] = None  # best-guess date/timestamp col for range filtering
    # Unity Catalog tables that consume this target (downstream blast radius). Populated
    # by the lineage pass so the report can prioritize a fix by how far a defect propagates.
    downstream_tables: list[str] = field(default_factory=list)
    # Optional grounded, per-table plain-English summary authored by the Genie Code
    # synthesis layer (see rca_engine/synthesize.py). Empty unless synthesis ran; it is
    # description only — it never sets a verdict.
    narrative: str = ""

    @property
    def common_rows(self) -> int:
        return max(self.source_count - self.missing_in_target, 0)

    @property
    def matched_rows(self) -> int:
        return max(self.common_rows - self.absolute_mismatch, 0)

    @property
    def row_match_pct(self) -> float:
        """Share of source rows that exist in target AND match on all columns."""

        if self.source_count <= 0:
            return 100.0 if self.matched_rows == 0 else 0.0
        return round(100.0 * self.matched_rows / self.source_count, 2)


@dataclass
class RootCauseCluster:
    """A systemic root cause shared by several findings.

    Migration defects are rarely isolated: one mis-translated ``CAST``, a single
    session timezone, or one load filter surfaces as value mismatches across many
    columns and tables. Listing each column separately buries the *one* fix a reader
    must make. A cluster collapses those findings into a single actionable item with
    the impacted-columns list, so the report can lead with "fix this, resolve N
    findings across M columns".
    """

    category: RootCauseCategory
    verdict: Verdict
    signature: str                                     # human label of the shared mechanism
    remediation: str = ""
    recommended_owner: str = ""
    members: list[str] = field(default_factory=list)   # "table.column" locations
    tables: list[str] = field(default_factory=list)    # distinct target tables spanned
    finding_count: int = 0
    rows_impacted: int = 0
    confidence: float = 0.0


@dataclass
class RcaResult:
    """The full RCA output for a recon run."""

    recon_id: str
    dialect: str
    findings: list[Finding] = field(default_factory=list)
    table_summaries: list[TableSummary] = field(default_factory=list)
    # Systemic causes that each explain several findings (built after drill-down).
    clusters: list[RootCauseCluster] = field(default_factory=list)
    # Optional grounded, run-level plain-English summary authored by the Genie Code
    # synthesis layer (see rca_engine/synthesize.py). Empty unless synthesis ran; it is
    # description only — verdicts stay deterministic + query-gated.
    narrative: str = ""

    def verdict_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {v.value: 0 for v in Verdict}
        for f in self.findings:
            top = f.top_hypothesis
            if top is not None:
                counts[top.verdict.value] += 1
        return counts
