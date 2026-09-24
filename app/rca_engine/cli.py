"""CLI entrypoint used by the Genie Code skill's ``scripts/run_rca.py``.

Runs the deterministic first pass: ingest -> classify -> emit findings JSON,
TL;DR, and an RCA notebook scaffold. The live drill-down happens inside Genie
Code after this produces its starting point.
"""

from __future__ import annotations

import argparse
import os
import sys

from rca_engine.report import build_tldr, write_rca_bundle


def _build_runner(profile: str | None, warehouse_id: str | None):
    """Construct a QueryRunner.

    Inside a Databricks notebook a ``spark`` session is in scope, so the Genie
    Code skill uses ``SparkQueryRunner(spark)`` directly. For local CLI runs we
    use the SQL Statement Execution API via the ``databricks`` CLI.
    """

    from rca_engine.runners import StatementRunner

    if not warehouse_id:
        raise SystemExit("--warehouse-id is required for local CLI runs.")
    return StatementRunner(warehouse_id=warehouse_id, profile=profile or "ps-dr-east")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RCA on a Lakebridge reconcile run.")
    parser.add_argument("--recon-id", default=None,
                        help="The reconcile run to analyze. Omit with --list to discover one.")
    parser.add_argument("--list", action="store_true",
                        help="List recent reconcile runs (pick a recon_id) and exit.")
    parser.add_argument("--recon-catalog", required=True)
    parser.add_argument("--recon-schema", required=True)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--output-dir", default="rca_output",
                        help="Base directory; a self-contained rca_<recon_id>/ folder is created "
                             "inside it (index + per-table notebooks + findings JSON).")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--warehouse-id", default=None)
    parser.add_argument("--no-drilldown", action="store_true",
                        help="Skip live confirmation queries (deterministic pass only).")
    parser.add_argument("--endpoint", default=None,
                        help="Foundation Model serving endpoint (e.g. databricks-claude-opus-5) for "
                             "the Tier-2 LLM fallback on residual (needs-review/unknown) findings. "
                             "Each hypothesis is still gated by an executed confirming query. Omit to "
                             "run the deterministic pass only.")
    parser.add_argument("--max-llm-findings", type=int, default=25,
                        help="Cap how many residual findings the --endpoint fallback attempts (default 25).")
    parser.add_argument("--recon-config", default=None,
                        help="Lakebridge reconcile config JSON (join keys, column mapping, filters).")
    parser.add_argument("--transpiled-output", default=None,
                        help="Folder/file of transpiled/target Databricks SQL (for code-level RCA).")
    parser.add_argument("--transpile-errors", default=None,
                        help="Lakebridge transpile error file (--error-file-path output).")
    parser.add_argument("--source-scripts", default=None,
                        help="Folder/file of original source DDL (declared source types).")
    parser.add_argument("--table-manifest", default=None,
                        help="YAML/JSON with an explicit per-table source/target script mapping.")
    parser.add_argument("--use-lineage", action="store_true",
                        help="Attach UC lineage evidence (system.access.*_lineage) when available, "
                             "including a depth-agnostic upstream trace-back to the root layer.")
    parser.add_argument("--max-lineage-hops", type=int, default=10,
                        help="Safety budget for the upstream lineage trace-back depth (default 10).")
    parser.add_argument("--trace-job", action="store_true",
                        help="Job-level trace: for each column mismatch, find the job that builds the "
                             "target (via system.access.table_lineage, or --job-id), parse its ETL SQL "
                             "and trace the column back to its true source columns + a reproduction query.")
    parser.add_argument("--job-id", default=None,
                        help="Explicit job id/name that builds the target table(s), used by --trace-job "
                             "when system-table discovery is unavailable.")
    parser.add_argument("--combined-notebook", action="store_true",
                        help="Also write a single-scroll combined notebook (rca_<id>_all.ipynb) "
                             "alongside the per-table notebooks.")
    args = parser.parse_args(argv)

    runner = _build_runner(args.profile, args.warehouse_id)

    if args.list:
        from rca_engine.discovery import format_recon_runs, list_recon_runs
        runs = list_recon_runs(runner, args.recon_catalog, args.recon_schema)
        print(format_recon_runs(runs))
        return 0

    if not args.recon_id:
        raise SystemExit("--recon-id is required (or use --list to discover one).")

    from rca_engine.analyze import analyze

    manifest = None
    if args.table_manifest:
        import yaml
        loaded = yaml.safe_load(open(args.table_manifest))
        manifest = loaded.get("tables", loaded) if isinstance(loaded, dict) else loaded

    mapping = None
    if any((args.recon_config, args.transpiled_output, args.transpile_errors,
            args.source_scripts, manifest)):
        from rca_engine.lakebridge import build_mapping
        mapping = build_mapping(args.recon_config, args.transpiled_output, args.transpile_errors,
                                source_scripts=args.source_scripts, source_dialect=args.dialect,
                                table_manifest=manifest)

    result = analyze(
        runner, args.recon_id, args.recon_catalog, args.recon_schema,
        dialect=args.dialect, drilldown=not args.no_drilldown, mapping=mapping,
        use_lineage=args.use_lineage, max_lineage_hops=args.max_lineage_hops,
        trace_job=args.trace_job, job_id=args.job_id, profile=args.profile,
    )

    # Optional Tier-2 LLM fallback on residual findings (still query-gated). Runs before
    # the bundle is written so the notebook/JSON reflect any promoted verdicts.
    if args.endpoint:
        from rca_engine.llm_fallback import run_llm_fallback
        promoted = run_llm_fallback(
            result, runner, args.endpoint, dialect=args.dialect, mapping=mapping,
            profile=args.profile, max_findings=args.max_llm_findings,
        )
        print(f"[llm] promoted {promoted} residual finding(s) via the confirming-query gate.")

    os.makedirs(args.output_dir, exist_ok=True)
    folder = write_rca_bundle(result, args.output_dir, args.recon_id,
                              combined=args.combined_notebook)
    print(build_tldr(result))
    print(f"\nArtifacts in: {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
