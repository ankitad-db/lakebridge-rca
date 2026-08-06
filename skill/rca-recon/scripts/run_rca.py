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

# ``rca_engine`` is vendored inside this skill folder (skill/rca-recon/rca_engine),
# so it imports directly from the workspace — no ``pip install`` from an external URL.
_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from rca_engine.analyze import analyze
from rca_engine.audit import log_audit
from rca_engine.discovery import format_recon_runs, list_recon_runs
from rca_engine.report import build_tldr, write_rca_bundle
from rca_engine.runners import SparkQueryRunner


def list_runs(spark: Any, limit: int = 20) -> None:
    """Step 0 — print recent reconcile runs so the user can pick a recon_id."""
    cfg = _load_config()
    runs = list_recon_runs(SparkQueryRunner(spark), cfg["recon_catalog"],
                           cfg["recon_schema"], limit=limit)
    print(format_recon_runs(runs))


def _audit_table(cfg: dict[str, Any]) -> str:
    """Fully-qualified audit table. ``audit_table: off`` disables it; otherwise it
    defaults to ``<recon_catalog>.<recon_schema>.rca_genie_audit``."""
    val = str(cfg.get("audit_table", "") or "").strip()
    if val.lower() in ("off", "none", "false", "disabled"):
        return ""
    if val:
        return val
    cat = cfg.get("recon_catalog")
    return f"{cat}.{cfg.get('recon_schema', 'reconcile')}.rca_genie_audit" if cat else ""


def _memory_table(cfg: dict[str, Any]) -> str:
    """Fully-qualified learning-loop memory table, or "" when disabled. ``use_memory``
    must be truthy to enable it; ``memory_table: off`` also disables. Defaults to
    ``<recon_catalog>.<recon_schema>.rca_genie_memory``."""
    if not cfg.get("use_memory"):
        return ""
    val = str(cfg.get("memory_table", "") or "").strip()
    if val.lower() in ("off", "none", "false", "disabled"):
        return ""
    if val:
        return val
    cat = cfg.get("recon_catalog")
    return f"{cat}.{cfg.get('recon_schema', 'reconcile')}.rca_genie_memory" if cat else ""


def _current_user(spark: Any) -> str:
    try:
        return spark.sql("SELECT current_user() AS u").collect()[0][0]
    except Exception:
        return ""


def _load_config() -> dict[str, Any]:
    """Load config.yml, then overlay any overrides from the ``RCA_CONFIG_JSON`` env var.

    The env overlay lets a headless caller (e.g. the Databricks App submitting this
    skill as a job) parameterize the run — recon_catalog / recon_schema / dialect /
    output_dir / audit_table — without editing config.yml, while the skill code stays
    the single source of truth for *what* happens.
    """
    cfg: dict[str, Any] = {}
    # PyYAML isn't in every runtime (e.g. serverless base env). config.yml reading is
    # therefore best-effort: when a headless caller supplies RCA_CONFIG_JSON, we don't
    # need the file at all.
    try:
        import yaml

        here = Path(__file__).resolve().parent.parent
        for candidate in (here / "config.yml", Path("config.yml")):
            if candidate.exists():
                cfg = yaml.safe_load(candidate.read_text()) or {}
                break
    except Exception:
        cfg = {}
    if not cfg:
        cfg = {"recon_catalog": "fevm_ps_dr_us_east_2_catalog", "recon_schema": "reconcile",
               "dialect": "snowflake", "output_dir": "rca_notebooks"}
    override = os.environ.get("RCA_CONFIG_JSON", "").strip()
    if override:
        import json as _json
        try:
            cfg.update({k: v for k, v in (_json.loads(override) or {}).items() if v not in (None, "")})
        except Exception:
            pass
    return cfg


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


def run(recon_id: str, spark: Any, out_dir: str | None = None, _run_id: str | None = None,
        only_table: str | None = None):
    """Run the end-to-end RCA and write artifacts.

    ``out_dir`` (where the notebook + JSON are written) is resolved in priority
    order: explicit argument > ``output_dir`` in config.yml > ``rca_notebooks``.
    A bare folder name resolves under the user's ``/Workspace/Users`` home; pass an
    absolute path (e.g. a UC Volume) to override.

    Use this directly to run RCA on an existing ``recon_id`` (the separate RCA path).
    ``reconcile_and_run`` calls it after triggering a reconcile. ``_run_id`` groups the
    audit row with a preceding reconcile step. ``only_table`` scopes the analysis to a
    single target table (one-table-at-a-time).
    """

    import time as _time
    started = _time.time()
    cfg = _load_config()
    out_dir = _resolve_out_dir(out_dir or cfg.get("output_dir") or "rca_notebooks", spark)
    os.makedirs(out_dir, exist_ok=True)

    # Optionally load Lakebridge transpile + recon-config artifacts for code-aware RCA.
    mapping = None
    if any(cfg.get(k) for k in ("recon_config_path", "transpiled_output_dir",
                                "transpile_error_file", "source_scripts_dir", "tables")):
        from rca_engine.lakebridge import build_mapping
        mapping = build_mapping(
            cfg.get("recon_config_path"),
            cfg.get("transpiled_output_dir"),
            cfg.get("transpile_error_file"),
            source_scripts=cfg.get("source_scripts_dir"),
            source_dialect=cfg.get("dialect", "snowflake"),
            table_manifest=cfg.get("tables"),
        )

    runner = SparkQueryRunner(spark)
    use_lineage = bool(cfg.get("use_uc_lineage", False))

    # Scan scoping: keep the live confirming/drift/fix-validation queries cheap by binding
    # them to the reconciliation-flagged keys and (optionally) a partition/date window,
    # instead of full-scanning source and target. Defaults to "scoped".
    from rca_engine.scan import ScanScope
    scope = ScanScope(
        mode=str(cfg.get("scan_mode", "scoped")),
        partition_column=str(cfg.get("scan_partition_column", "") or ""),
        date_start=str(cfg.get("scan_date_start", "") or ""),
        date_end=str(cfg.get("scan_date_end", "") or ""),
        max_keys=int(cfg.get("scan_max_keys", 500)),
    )

    # Learning loop: load priors from previously-confirmed runs so recurring causes are
    # proposed (and then confirmed by the drill-down). Off unless use_memory is set.
    dialect = cfg.get("dialect", "snowflake")
    mem_table = _memory_table(cfg)
    memory = None
    if mem_table:
        from rca_engine.memory import load_memory
        memory = load_memory(runner, mem_table, dialect=dialect)

    result = analyze(
        runner, recon_id, cfg["recon_catalog"], cfg["recon_schema"],
        dialect=cfg.get("dialect", "snowflake"), drilldown=True, mapping=mapping,
        use_lineage=use_lineage,
        # Depth of the upstream lineage trace-back (walks to the root layer).
        max_lineage_hops=int(cfg.get("max_lineage_hops", 10)),
        only_table=only_table,
        # Quantify each column's source-vs-target distribution shift (on by default).
        drift=bool(cfg.get("distribution_drift", True)),
        # Downstream blast radius needs UC lineage; default it to whether lineage is on.
        blast_radius=bool(cfg.get("blast_radius", use_lineage)),
        # Attach concrete, runnable suggested fixes to findings (on by default).
        fixes=bool(cfg.get("suggest_fixes", True)),
        # Fix-validation gate: run each fix's validation query to mark it validated.
        validate_fixes=bool(cfg.get("validate_fixes", True)),
        # Learned priors from prior confirmed runs (None unless use_memory is set).
        memory=memory,
        # Bound the live source/target scans (flagged keys + partition window).
        scope=scope,
    )

    # One self-contained folder per recon run: rca_<id>/ with 00_index.ipynb, the
    # findings JSON, and one notebook per reconciled table (see write_rca_bundle).
    folder = write_rca_bundle(result, out_dir, recon_id,
                              combined=bool(cfg.get("combined_notebook", False)))

    # Learning loop: remember every query-confirmed cause so it auto-proposes next time.
    if mem_table:
        from rca_engine.memory import record_confirmations
        n_learned = record_confirmations(runner, mem_table, result, dialect,
                                         run_by=_current_user(spark))
        if n_learned:
            print(f"Learned {n_learned} confirmed cause(s) into {mem_table}")

    with_diffs = sum(1 for s in result.table_summaries
                     if s.missing_in_source or s.missing_in_target
                     or s.absolute_mismatch or not s.schema_ok)
    log_audit(runner, _audit_table(cfg), operation="rca", status="ok", tool="skill",
              run_id=_run_id, run_by=_current_user(spark), catalog=cfg.get("recon_catalog"),
              recon_id=recon_id, table_pairs=len(result.table_summaries),
              tables_with_diffs=with_diffs, findings_total=len(result.findings),
              notebook_path=folder, message="RCA complete.", started_ts=started)

    print(build_tldr(result))
    print(f"\nArtifacts in: {folder}")
    print(f"  open {os.path.join(folder, '00_index.ipynb')} to route each table")
    return result


def _to_specs(tables: Any):
    """Normalize the ``tables`` arg into TablePairSpec list. Each item may be a bare
    string (source==target) or a dict ``{source, target?, join_keys?, column_mapping?}``."""
    from rca_engine.reconcile import TablePairSpec

    specs = []
    for t in tables or []:
        if isinstance(t, str):
            specs.append(TablePairSpec(source_table=t.strip()))
            continue
        src = (t.get("source") or t.get("source_table") or "").strip()
        if not src:
            continue
        specs.append(TablePairSpec(
            source_table=src,
            target_table=(t.get("target") or t.get("target_table") or "").strip(),
            join_keys=[k for k in (t.get("join_keys") or []) if k],
            column_mapping={k: v for k, v in (t.get("column_mapping") or {}).items() if k and v},
        ))
    return specs


def reconcile(spark: Any, source_schema: str, target_schema: str, tables: Any,
              max_key_tries: int = 8, sample_limit: int = 100):
    """Trigger an app-native reconcile of ``tables`` (source_schema vs target_schema)
    and return the ``ReconRunResult`` (its ``recon_id`` feeds ``run``).

    Join keys are auto-detected when omitted (capped at ``max_key_tries``); renamed
    columns go through each pair's ``column_mapping``; per-pair errors are isolated so
    one bad pair never sinks the run. Writes Lakebridge-compatible main/metrics/details
    rows under the fresh ``recon_id`` in ``<recon_catalog>.<recon_schema>``.
    """

    import time as _time

    from rca_engine.reconcile import run_reconcile

    cfg = _load_config()
    started = _time.time()
    runner = SparkQueryRunner(spark)
    specs = _to_specs(tables)
    if not specs:
        raise ValueError("No tables provided to reconcile.")
    result = run_reconcile(runner, cfg["recon_catalog"], source_schema, target_schema, specs,
                           recon_schema=cfg.get("recon_schema", "reconcile"),
                           sample_limit=sample_limit, max_key_tries=max_key_tries)
    summary = result.to_dict()
    run_id = log_audit(runner, _audit_table(cfg), operation="reconcile",
                       status="ok" if summary["pairs_ok"] else "error", tool="skill",
                       run_by=_current_user(spark), catalog=cfg["recon_catalog"],
                       source_schema=source_schema, target_schema=target_schema,
                       recon_id=result.recon_id, tables=summary["pairs"], table_pairs=len(specs),
                       pairs_ok=summary["pairs_ok"], pairs_error=summary["pairs_error"],
                       message=f"Reconciled {summary['pairs_ok']}/{len(specs)} pair(s).",
                       started_ts=started)
    result._audit_run_id = run_id  # type: ignore[attr-defined]  # group the RCA row
    print(f"recon_id: {result.recon_id}  ·  {summary['pairs_ok']} ok / {summary['pairs_error']} error")
    for p in summary["pairs"]:
        flag = "✅" if p["status"] == "ok" else "⚠️"
        print(f"  {flag} {p['source_table']} → {p['target_table']}: {p['message']}")
    return result


def reconcile_and_run(spark: Any, source_schema: str, target_schema: str, tables: Any,
                      out_dir: str | None = None, max_key_tries: int = 8, sample_limit: int = 100):
    """One-call pipeline: reconcile ``tables`` then run the full RCA on the resulting
    ``recon_id``. Returns ``(recon_id, RcaResult)``. To run RCA on an existing recon
    instead, skip this and call ``run(recon_id, spark)`` directly."""
    recon = reconcile(spark, source_schema, target_schema, tables,
                      max_key_tries=max_key_tries, sample_limit=sample_limit)
    if not any(p.status == "ok" for p in recon.pairs):
        raise RuntimeError("Reconcile produced no comparable pairs — see per-table errors above.")
    run_id = getattr(recon, "_audit_run_id", None)
    result = run(recon.recon_id, spark, out_dir, _run_id=run_id)
    return recon.recon_id, result


if __name__ == "__main__":
    import sys

    try:
        _spark = spark  # type: ignore  # provided by the Databricks notebook
    except NameError as exc:  # pragma: no cover
        raise SystemExit("Run this inside a Databricks notebook where `spark` exists.") from exc
    _recon = sys.argv[1] if len(sys.argv) > 1 else input("recon_id: ")
    _out = sys.argv[2] if len(sys.argv) > 2 else None
    run(_recon, _spark, _out)
