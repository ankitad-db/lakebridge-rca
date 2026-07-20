"""CLI entrypoint used by the Genie Code skill's ``scripts/run_rca.py``.

Runs the deterministic first pass: ingest -> classify -> emit findings JSON,
TL;DR, and an RCA notebook scaffold. The live drill-down happens inside Genie
Code after this produces its starting point.
"""

from __future__ import annotations

import argparse
import sys

from rca_engine.classify import classify_all
from rca_engine.models import RcaResult
from rca_engine.report import build_tldr, write_json, write_notebook


def _build_runner(profile: str | None):
    """Construct a Databricks-backed QueryRunner. Imported lazily so the core
    package has no hard dependency on the connector."""

    from databricks import sql  # type: ignore

    raise NotImplementedError(
        "Wire the Databricks SQL connection (host/http_path/token or profile) here in Phase 3."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RCA on a Lakebridge reconcile run.")
    parser.add_argument("--recon-id", required=True)
    parser.add_argument("--recon-catalog", required=True)
    parser.add_argument("--recon-schema", required=True)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--output-path", default="rca_output")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args(argv)

    runner = _build_runner(args.profile)

    from rca_engine.ingest import ingest

    findings = ingest(runner, args.recon_id, args.recon_catalog, args.recon_schema)
    findings = classify_all(findings, dialect=args.dialect)
    result = RcaResult(recon_id=args.recon_id, dialect=args.dialect, findings=findings)

    write_json(result, f"{args.output_path}.json")
    write_notebook(result, f"{args.output_path}.ipynb")
    print(build_tldr(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
