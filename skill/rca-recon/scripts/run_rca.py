"""Deterministic first-pass RCA for a Lakebridge reconcile run.

Designed to run inside a Databricks notebook (Genie Code), where a ``spark``
session is in scope. Produces findings JSON, a TL;DR, and an RCA notebook
scaffold that the agent then enriches with live drill-down queries.

Usage in a notebook cell:
    %run ./scripts/run_rca.py                 # if imported as a module, call run(...)
or:
    from scripts.run_rca import run
    result = run("0fe6053f...", spark)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml

# ``rca_engine`` is vendored inside this skill folder (skill/rca-recon/rca_engine),
# so it imports directly from the workspace — no ``pip install`` from an external URL.
_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from rca_engine.analyze import analyze
from rca_engine.report import build_tldr, write_json, write_notebook
from rca_engine.runners import SparkQueryRunner


def _load_config() -> dict[str, Any]:
    here = Path(__file__).resolve().parent.parent
    for candidate in (here / "config.yml", Path("config.yml")):
        if candidate.exists():
            return yaml.safe_load(candidate.read_text()) or {}
    return {"recon_catalog": "fevm_ps_dr_us_east_2_catalog", "recon_schema": "reconcile",
            "dialect": "snowflake", "output_dir": "/tmp"}


def run(recon_id: str, spark: Any, out_dir: str | None = None):
    """Run the end-to-end RCA and write artifacts.

    ``out_dir`` (where the notebook + JSON are written) is resolved in priority
    order: explicit argument > ``output_dir`` in config.yml > ``/tmp``. The user
    can point it at a UC Volume or workspace path for a durable copy.
    """

    cfg = _load_config()
    out_dir = out_dir or cfg.get("output_dir") or "/tmp"
    os.makedirs(out_dir, exist_ok=True)

    runner = SparkQueryRunner(spark)
    result = analyze(
        runner, recon_id, cfg["recon_catalog"], cfg["recon_schema"],
        dialect=cfg.get("dialect", "snowflake"), drilldown=True,
    )

    base = os.path.join(out_dir, f"rca_{recon_id}")
    write_json(result, f"{base}.json")
    write_notebook(result, f"{base}.ipynb")
    print(build_tldr(result))
    print(f"\nArtifacts: {base}.json  {base}.ipynb")
    return result


if __name__ == "__main__":
    import sys

    try:
        _spark = spark  # type: ignore  # provided by the Databricks notebook
    except NameError as exc:  # pragma: no cover
        raise SystemExit("Run this inside a Databricks notebook where `spark` exists.") from exc
    _recon = sys.argv[1] if len(sys.argv) > 1 else input("recon_id: ")
    _out = sys.argv[2] if len(sys.argv) > 2 else None
    run(_recon, _spark, _out)
