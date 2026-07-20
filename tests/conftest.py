"""Shared pytest fixtures/helpers for the RCA engine tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from rca_engine.models import Finding, MismatchSample, ReconType

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_PATH = REPO_ROOT / "migration" / "scenarios.yaml"


def load_scenarios() -> list[dict]:
    return yaml.safe_load(SCENARIOS_PATH.read_text())["scenarios"]


def make_column_finding(column: str, source, target, *, n: int = 5,
                        total: int = 100, table: str = "tgt") -> Finding:
    """A COLUMN_MISMATCH finding with ``n`` identical sampled value pairs."""

    samples = [
        MismatchSample(keys={"id": i}, column=column, source_value=source, target_value=target)
        for i in range(n)
    ]
    return Finding(
        recon_id="test", source_table="src", target_table=table,
        recon_type=ReconType.COLUMN_MISMATCH, column=column,
        mismatch_count=n, total_count=total, samples=samples,
    )
