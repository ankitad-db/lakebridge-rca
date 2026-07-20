"""CLI entrypoint used by the Genie Code skill's ``scripts/run_rca.py``.

Runs the deterministic first pass: ingest -> classify -> emit findings JSON,
TL;DR, and an RCA notebook scaffold. The live drill-down happens inside Genie
Code after this produces its starting point.
"""

from __future__ import annotations

import argparse
import os
import sys

from rca_engine.report import build_tldr, write_json, write_notebook


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
    parser.add_argument("--recon-id", required=True)
    parser.add_argument("--recon-catalog", required=True)
    parser.add_argument("--recon-schema", required=True)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--output-path", default="rca_output",
                        help="Base path for the generated .json/.ipynb (dirs are created).")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--warehouse-id", default=None)
    parser.add_argument("--no-drilldown", action="store_true",
                        help="Skip live confirmation queries (deterministic pass only).")
    parser.add_argument("--recon-config", default=None,
                        help="Lakebridge reconcile config JSON (join keys, column mapping, filters).")
    parser.add_argument("--transpiled-output", default=None,
                        help="Folder/file of transpiled/target Databricks SQL (for code-level RCA).")
    parser.add_argument("--transpile-errors", default=None,
                        help="Lakebridge transpile error file (--error-file-path output).")
    parser.add_argument("--source-scripts", default=None,
                        help="Folder/file of original source DDL (declared source types).")
    args = parser.parse_args(argv)

    runner = _build_runner(args.profile, args.warehouse_id)

    from rca_engine.analyze import analyze

    mapping = None
    if args.recon_config or args.transpiled_output or args.transpile_errors or args.source_scripts:
        from rca_engine.lakebridge import build_mapping
        mapping = build_mapping(args.recon_config, args.transpiled_output, args.transpile_errors,
                                source_scripts=args.source_scripts, source_dialect=args.dialect)

    result = analyze(
        runner, args.recon_id, args.recon_catalog, args.recon_schema,
        dialect=args.dialect, drilldown=not args.no_drilldown, mapping=mapping,
    )

    parent = os.path.dirname(args.output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    write_json(result, f"{args.output_path}.json")
    write_notebook(result, f"{args.output_path}.ipynb")
    print(build_tldr(result))
    print(f"\nArtifacts: {args.output_path}.json  {args.output_path}.ipynb")
    return 0


if __name__ == "__main__":
    sys.exit(main())
