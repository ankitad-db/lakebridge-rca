"""Run REAL deterministic RCA on every recon_id in ps-dr-east `main` and write each bundle
into app/bundles/ — so the Migration Health dashboard shows authentic results (verdict mix,
recurring causes) across the whole recon history, not seeded data.

Best-effort per recon: a recon whose source/target tables were dropped still classifies from
its stored recon details (confirming queries just can't run — those findings stay
needs-review). Lean pass (no lineage, no LLM) to stay fast across many recons.

  python3 migration/run_rca_all.py [--limit N]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rca_engine.analyze import analyze  # noqa: E402
from rca_engine.discovery import list_recon_runs  # noqa: E402
from rca_engine.report import to_dict, write_json  # noqa: E402
from rca_engine.runners import StatementRunner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLES = os.path.join(ROOT, "app", "bundles")
CATALOG = "fevm_ps_dr_us_east_2_catalog"
SCHEMA = "reconcile"
WAREHOUSE = "4c79c6902dd2bbc2"
PROFILE = "ps-dr-east"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--endpoint", default=None,
                    help="FM endpoint → run HYBRID (deterministic + agentic Tier-2 fallback).")
    ap.add_argument("--only", default=None, help="Comma-separated recon_ids to (re)run.")
    a = ap.parse_args()

    runner = StatementRunner(warehouse_id=WAREHOUSE, profile=PROFILE)
    only = {x.strip() for x in a.only.split(",")} if a.only else None
    runs = list_recon_runs(runner, CATALOG, SCHEMA, limit=a.limit)
    if only:
        runs = [r for r in runs if r.get("recon_id") in only]
    mode = f"HYBRID via {a.endpoint}" if a.endpoint else "DETERMINISTIC"
    print(f"Found {len(runs)} recon_id(s) to run ({mode})\n")

    ok = fail = 0
    for r in runs:
        rid = r.get("recon_id")
        started = r.get("started")
        if not rid:
            continue
        t0 = time.time()
        try:
            result = analyze(
                runner, rid, CATALOG, SCHEMA,
                dialect="snowflake", drilldown=True,
                use_lineage=False,   # lean: skip lineage for speed/reliability across many recons
            )
            # HYBRID: engage the agentic Tier-2 fallback on residual findings (query-gated).
            if a.endpoint:
                try:
                    from rca_engine.llm_fallback import run_llm_fallback
                    run_llm_fallback(result, runner, a.endpoint, dialect="snowflake",
                                     profile=PROFILE, max_findings=25)
                except Exception as _e:
                    print(f"    [hybrid] fallback skipped: {str(_e)[:70]}")
            n = len(result.findings)
            folder = os.path.join(BUNDLES, f"rca_{rid}")
            os.makedirs(folder, exist_ok=True)
            write_json(result, os.path.join(folder, f"rca_{rid}.json"))
            with open(os.path.join(folder, "meta.json"), "w") as fh:
                json.dump({"started": str(started) if started else None,
                           "source": "Snowflake → Databricks migration"}, fh)
            v: dict[str, int] = {}
            for f in result.findings:
                h = f.top_hypothesis
                if h:
                    v[h.verdict.value] = v.get(h.verdict.value, 0) + 1
            print(f"  ✓ {rid[:12]}…  {n:2d} findings  {v}  ({time.time() - t0:.0f}s)")
            ok += 1
        except Exception as exc:
            print(f"  ✗ {rid[:12]}…  {str(exc)[:80]}  ({time.time() - t0:.0f}s)")
            fail += 1

    print(f"\nDone: {ok} bundle(s) written, {fail} failed.")
    print("Total recon bundles now:", len([d for d in os.listdir(BUNDLES) if d.startswith('rca_')]))


if __name__ == "__main__":
    main()
