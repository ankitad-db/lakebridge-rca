"""rca_engine: source-agnostic root-cause analysis for migration reconciliation.

Pipeline: ingest recon output -> probes + row-pattern + code correlation + KB
-> classify (verdict + category + confidence) -> report (findings + notebook).
"""

from rca_engine.models import (
    Evidence,
    Finding,
    Hypothesis,
    MismatchSample,
    RcaResult,
    ReconType,
    RootCauseCategory,
    Verdict,
)
from rca_engine.resolve import (
    build_evidence_bundle,
    resolve_finding,
    unresolved_findings,
)

__all__ = [
    "Evidence",
    "Finding",
    "Hypothesis",
    "MismatchSample",
    "RcaResult",
    "ReconType",
    "RootCauseCategory",
    "Verdict",
    "build_evidence_bundle",
    "resolve_finding",
    "unresolved_findings",
]

__version__ = "0.1.0"
