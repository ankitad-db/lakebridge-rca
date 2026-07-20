#!/usr/bin/env python3
"""Integration validation harness.

Runs the full RCA (`analyze`) against a real Lakebridge recon run and checks the
produced category/verdict for every *deployed* scenario against the ground-truth
oracle in ``migration/scenarios.yaml``. Prints a PASS/FAIL matrix and exits
non-zero on any mismatch — suitable for CI once a recon_id is available.

Usage:
  python scripts/validate_scenarios.py --recon-id <id> --warehouse-id <wid> \
      [--recon-catalog C] [--recon-schema S] [--profile P]

This needs workspace access (a SQL warehouse); it is intentionally NOT a pytest
test. The deterministic, workspace-free coverage lives in tests/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from rca_engine.analyze import analyze  # noqa: E402
from rca_engine.lakebridge import build_mapping, parse_transpiled_dir  # noqa: E402
from rca_engine.models import ReconType  # noqa: E402
from rca_engine.runners import StatementRunner  # noqa: E402

_ROW_TYPES = {
    "missing_in_target": ReconType.MISSING_IN_TARGET,
    "missing_in_source": ReconType.MISSING_IN_SOURCE,
    "schema": ReconType.SCHEMA,
}


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`").lower() if name else ""


def _find(findings, sc):
    table, col = sc["table"].lower(), sc.get("column")
    for f in findings:
        if _short(f.target_table) != table:
            continue
        if col and f.recon_type == ReconType.COLUMN_MISMATCH and (f.column or "").lower() == col.lower():
            return f
        if not col and f.recon_type == _ROW_TYPES.get(sc["recon_type"]):
            return f
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--recon-id", required=True)
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--recon-catalog", default="fevm_ps_dr_us_east_2_catalog")
    p.add_argument("--recon-schema", default="reconcile")
    p.add_argument("--profile", default="ps-dr-east")
    p.add_argument("--dialect", default="snowflake")
    args = p.parse_args(argv)

    mapping = build_mapping(
        recon_config_path=REPO / "migration/recon/30_reconcile_config.json",
        transpiled_output=REPO / "migration/pipeline",
        source_scripts=REPO / "migration/source_sql",
        source_dialect=args.dialect,
    )
    for k, m in parse_transpiled_dir(REPO / "migration/edge_cases").items():
        mapping.setdefault(k, m).transforms.update(m.transforms)

    runner = StatementRunner(warehouse_id=args.warehouse_id, profile=args.profile)
    result = analyze(runner, args.recon_id, args.recon_catalog, args.recon_schema,
                     dialect=args.dialect, drilldown=True, mapping=mapping)

    scenarios = [s for s in yaml.safe_load(
        (REPO / "migration/scenarios.yaml").read_text())["scenarios"] if s.get("deployed")]

    passed = failed = 0
    print(f"{'id':5} {'table.col':32} {'got cat/verdict':34} {'expected':30} result")
    print("-" * 110)
    for sc in scenarios:
        loc = sc["table"] + (f".{sc['column']}" if sc.get("column") else f" ({sc['recon_type']})")
        if sc["recon_type"] == "none":  # clean baseline: expect zero findings for the table
            hits = [f for f in result.findings if _short(f.target_table) == sc["table"].lower()]
            ok = not hits
            got = "no findings" if ok else f"{len(hits)} finding(s)"
            exp = "clean"
        else:
            f = _find(result.findings, sc)
            top = f.top_hypothesis if f else None
            got_cat = top.category.value if top else "MISSING"
            got_ver = top.verdict.value if top else "-"
            got = f"{got_cat}/{got_ver}"
            exp = f"{sc['category']}/{sc['verdict']}"
            # category must match; verdict must match unless the scenario is category-only
            ok = got_cat == sc["category"] and (
                got_ver == sc["verdict"] or sc.get("verdict_flexible"))
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"{sc['id']:5} {loc:32} {got:34} {exp:30} {'PASS' if ok else 'FAIL'}")

    print("-" * 110)
    print(f"{passed} passed, {failed} failed, of {len(scenarios)} deployed scenarios")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
