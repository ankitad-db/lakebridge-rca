"""Run our validation-tool-agnostic RCA over an AVF run and write a bundle to app/bundles/.

This is the AVF counterpart of run_rca_revenue.py: instead of ingesting Lakebridge recon
output, it points analyze() at an :class:`AVFSource`, which reads the avf_* report tables
for the given run_id. The source dialect is AUTO-DETECTED from avf_validation_summary
(teradata, in the real project) so the right knowledge base loads; AVF's own row-count RCA
is folded in as evidence.

  python migration/avf_demo/run_rca_avf.py <run_id> \
      [--reports-schema fevm_ps_dr_us_east_2_catalog.avf_reports] \
      [--endpoint databricks-claude-opus-5]      # hybrid (query-gated Tier-2); omit = deterministic

Code-aware RCA (optional): the project's source + migrated SQL live in GitHub. Pass local
checkouts (or Databricks Git-folder paths) via --code-dir / --source-dir to attach the
🔧 migrated-transform logic and source-vs-target lineage to each finding.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rca_engine.analyze import analyze  # noqa: E402
from rca_engine.report import write_json  # noqa: E402
from rca_engine.runners import StatementRunner  # noqa: E402
from rca_engine.sources import AVFSource  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLES = os.path.join(ROOT, "app", "bundles")
CAT = "fevm_ps_dr_us_east_2_catalog"
WAREHOUSE = "4c79c6902dd2bbc2"
PROFILE = "ps-dr-east"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--reports-schema", default=f"{CAT}.avf_reports",
                    help="catalog.schema holding the avf_* report tables.")
    ap.add_argument("--endpoint", default="",
                    help="FM endpoint for the hybrid Tier-2 fallback. Empty = deterministic only.")
    ap.add_argument("--code-dir", default="", help="Migrated (target) SQL dir for code-aware RCA.")
    ap.add_argument("--source-dir", default="", help="Source EDW SQL dir for source-vs-target.")
    a = ap.parse_args()

    runner = StatementRunner(warehouse_id=WAREHOUSE, profile=PROFILE)
    source = AVFSource(run_id=a.run_id, reports_schema=a.reports_schema, consume_rca=True)

    mapping = None
    if a.code_dir or a.source_dir:
        from rca_engine.lakebridge import build_mapping
        mapping = build_mapping(transpiled_output=a.code_dir or None,
                                source_transpiled=a.source_dir or None,
                                source_dialect="teradata")

    t0 = time.time()
    result = analyze(
        runner, "", "", "", source=source, mapping=mapping,
        drilldown=True, use_lineage=True, trace_job=False,
    )
    print(f"ingest+classify: {len(result.findings)} findings, dialect={result.dialect} "
          f"({time.time()-t0:.0f}s)")

    if a.endpoint:
        try:
            from rca_engine.llm_fallback import run_llm_fallback
            n = run_llm_fallback(result, runner, a.endpoint, dialect=result.dialect, profile=PROFILE)
            print(f"agentic Tier-2: {n} finding(s) promoted")
        except Exception as e:
            print(f"[hybrid] fallback skipped: {str(e)[:120]}")

    rid = result.recon_id
    folder = os.path.join(BUNDLES, f"rca_{rid}")
    os.makedirs(folder, exist_ok=True)
    write_json(result, os.path.join(folder, f"rca_{rid}.json"))
    with open(os.path.join(folder, "meta.json"), "w") as fh:
        json.dump({"started": None, "source": "AVF validation (Teradata → Databricks)"}, fh)

    v: dict[str, int] = {}
    for f in result.findings:
        h = f.top_hypothesis
        if h:
            v[h.verdict.value] = v.get(h.verdict.value, 0) + 1
    print(f"\n✓ {rid}  {len(result.findings)} findings  {v}")
    print(f"bundle: {folder}")


if __name__ == "__main__":
    main()
