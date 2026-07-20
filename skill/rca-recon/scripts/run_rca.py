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
            "dialect": "snowflake", "output_dir": "rca_notebooks"}


def _resolve_out_dir(out_dir: str, spark: Any) -> str:
    """Resolve where to write the RCA notebook.

    Absolute paths (``/Volumes/...``, ``/Workspace/...``, ``/tmp``) are used as-is.
    A bare folder name (the default) is placed under the current user's workspace
    home: ``/Workspace/Users/<current_user>/<folder>`` — a durable, per-user spot.
    """

    if out_dir.startswith("/"):
        return out_dir
    folder = out_dir or "rca_notebooks"
    try:
        user = spark.sql("SELECT current_user() AS u").collect()[0][0]
        return f"/Workspace/Users/{user}/{folder}"
    except Exception:
        return f"/tmp/{folder}"


def run(recon_id: str, spark: Any, out_dir: str | None = None):
    """Run the end-to-end RCA and write artifacts.

    ``out_dir`` (where the notebook + JSON are written) is resolved in priority
    order: explicit argument > ``output_dir`` in config.yml > ``rca_notebooks``.
    A bare folder name resolves under the user's ``/Workspace/Users`` home; pass an
    absolute path (e.g. a UC Volume) to override.
    """

    cfg = _load_config()
    out_dir = _resolve_out_dir(out_dir or cfg.get("output_dir") or "rca_notebooks", spark)
    os.makedirs(out_dir, exist_ok=True)

    # Optionally load Lakebridge transpile + recon-config artifacts for code-aware RCA.
    mapping = None
    if cfg.get("recon_config_path") or cfg.get("transpiled_output_dir") or cfg.get("transpile_error_file"):
        from rca_engine.lakebridge import build_mapping
        mapping = build_mapping(
            cfg.get("recon_config_path"),
            cfg.get("transpiled_output_dir"),
            cfg.get("transpile_error_file"),
        )

    runner = SparkQueryRunner(spark)
    result = analyze(
        runner, recon_id, cfg["recon_catalog"], cfg["recon_schema"],
        dialect=cfg.get("dialect", "snowflake"), drilldown=True, mapping=mapping,
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
