"""Code-aware HYBRID RCA for the focused REVENUE demo recon.

Parses revenue_target.sql for the per-column transform logic (so findings carry the
🔧 Transformation logic + 📄 script location + 🔗 lineage), runs the deterministic pass,
then engages the agentic Tier-2 fallback (query-gated) so the FX-grain HERO is
proposed + query-confirmed. Writes the bundle into app/bundles/.

  python migration/retail_demo/run_rca_revenue.py <recon_id> [--endpoint databricks-claude-opus-5]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rca_engine.analyze import analyze  # noqa: E402
from rca_engine.lakebridge import build_mapping  # noqa: E402
from rca_engine.report import write_json  # noqa: E402
from rca_engine.runners import StatementRunner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLES = os.path.join(ROOT, "app", "bundles")
# Repo-relative so the finding's "📄 Script location" reads as a clean repo path
# (migration/retail_demo/revenue_code/revenue_target.sql), not an absolute /Users/... path.
CODE_DIR = "migration/retail_demo/revenue_code"
SOURCE_CODE_DIR = "migration/retail_demo/revenue_source_code"
CATALOG = "fevm_ps_dr_us_east_2_catalog"
SCHEMA = "reconcile"
WAREHOUSE = "4c79c6902dd2bbc2"
PROFILE = "ps-dr-east"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recon_id")
    ap.add_argument("--endpoint", default="databricks-claude-opus-5",
                    help="FM endpoint for the agentic Tier-2 fallback. Empty = deterministic only.")
    ap.add_argument("--code-dir", default=CODE_DIR, help="Target (migrated) SQL dir for code-aware RCA.")
    ap.add_argument("--source-dir", default=SOURCE_CODE_DIR, help="Source EDW SQL dir for source-vs-target.")
    a = ap.parse_args()
    rid = a.recon_id

    runner = StatementRunner(warehouse_id=WAREHOUSE, profile=PROFILE)
    mapping = build_mapping(transpiled_output=a.code_dir, source_transpiled=a.source_dir,
                            source_dialect="snowflake")
    print(f"mapping tables: {sorted(mapping.keys())}")

    t0 = time.time()
    result = analyze(
        runner, rid, CATALOG, SCHEMA,
        dialect="snowflake", drilldown=True,
        mapping=mapping,
        use_lineage=True,      # UC column lineage evidence
        trace_job=False,       # target built via CTAS (not a job) — mapping supplies the code
    )
    print(f"deterministic pass: {len(result.findings)} findings ({time.time()-t0:.0f}s)")

    if a.endpoint:
        try:
            from rca_engine.llm_fallback import run_llm_fallback
            n = run_llm_fallback(result, runner, a.endpoint, dialect="snowflake",
                                 profile=PROFILE, max_findings=25)
            print(f"agentic Tier-2: {n} finding(s) promoted")
        except Exception as e:
            print(f"[hybrid] fallback skipped: {str(e)[:120]}")

    folder = os.path.join(BUNDLES, f"rca_{rid}")
    os.makedirs(folder, exist_ok=True)
    write_json(result, os.path.join(folder, f"rca_{rid}.json"))
    with open(os.path.join(folder, "meta.json"), "w") as fh:
        json.dump({"started": None, "source": "Snowflake → Databricks migration"}, fh)

    v: dict[str, int] = {}
    for f in result.findings:
        h = f.top_hypothesis
        if h:
            v[h.verdict.value] = v.get(h.verdict.value, 0) + 1
    print(f"\n✓ {rid}  {len(result.findings)} findings  {v}")
    print(f"bundle: {folder}")


if __name__ == "__main__":
    main()
