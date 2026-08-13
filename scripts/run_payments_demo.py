"""End-to-end driver for the DEMO PAYMENTS bed — the "two tiers" scenario.

Runs the whole story against a real workspace:

  1. Deploy the pipeline SQL (raw -> enriched -> gold + src).
  2. App-native reconcile payments_src -> payments_gold (fresh recon_id).
  3. Deterministic RCA (probes + drill-down + UC lineage + code-aware mapping).
  4. Tier-2 LLM fallback via a Claude Foundation Model endpoint for the residual
     (net_amount), which promotes the verdict only if its confirming query passes.

Prints a per-finding summary showing which tier concluded each finding.

Usage:
    python scripts/run_payments_demo.py \
        --profile ps-dr-east --warehouse-id 4c79c6902dd2bbc2 \
        --endpoint databricks-claude-opus-5 [--skip-deploy] [--recon-id <id>]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

CATALOG = "fevm_ps_dr_us_east_2_catalog"
SCHEMA = "mig_demo_payments"
RECON_SCHEMA = "reconcile"
PIPELINE_SQL = "migration/demo_payments/70_demo_payments_pipeline.sql"
MANIFEST = "migration/demo_payments/table_manifest.yml"

# Claude fallback system prompt (mirrors app/server/llm_fallback.py).
_SYSTEM = (
    "You are a migration reconciliation root-cause analyst. A deterministic engine has "
    "already classified the known mismatch mechanisms; you only see the residual findings "
    "it could not conclude. For ONE finding, propose the single most likely root-cause "
    "category and a SQL query that would CONFIRM it against the real source/target tables. "
    "You must not guess a verdict — the query is what proves it.\n\n"
    "Rules:\n"
    "- Use the fully-qualified table names given (source_table, target_table).\n"
    "- The query MUST return a boolean column named `confirmed` (and ideally an integer `n`).\n"
    "- `confirmed` MUST be TRUE exactly when your hypothesis holds, FALSE otherwise.\n"
    "- Prefer an EXACT reconstruction check over averages/ratios: reconstruct the target\n"
    "  column from the source columns using your hypothesized formula and assert every row\n"
    "  matches, e.g. `count_if(NOT (t.<col> <=> <formula over s.*>)) = 0 AS confirmed`.\n"
    "- The `target_derivation` field (when present) is the migrated expression that produced\n"
    "  the column — use it to form the hypothesized formula.\n"
    "- Keep it aggregate (counts / min / max / boolean) — never dump rows.\n"
    "- category must be one of: type_precision, timezone, semi_structured, string_format, "
    "transpilation, volume_missing, volume_extra, upstream_drift, null_boolean, env_config.\n"
    "- If the data really differs at the source, use category=upstream_drift and "
    "verdict=genuine_data.\n"
    "- If you cannot form a confident, testable hypothesis, set resolvable=false.\n\n"
    'Respond with ONLY a JSON object: {"resolvable": bool, "category": str, '
    '"verdict": "migration_induced"|"genuine_data"|"benign"|"needs_review", '
    '"rationale": str, "confirm_query": str}'
)


def _extract_json(text: str):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def deploy(runner) -> None:
    sql = open(os.path.join(REPO, PIPELINE_SQL)).read()
    # Strip line comments first so a ';' inside a comment never splits a statement.
    no_comments = "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())
    stmts = [s.strip() for s in no_comments.split(";") if s.strip()]
    print(f"[deploy] executing {len(stmts)} statements ...")
    for i, s in enumerate(stmts, 1):
        runner.query(s)
        first = next((l for l in s.splitlines() if l.strip()), "")
        print(f"  [{i}/{len(stmts)}] ok: {first.strip()[:70]}")


def reconcile(runner) -> str:
    from rca_engine.reconcile import TablePairSpec, run_reconcile

    print("[recon] reconciling payments_src -> payments_gold ...")
    res = run_reconcile(
        runner, CATALOG, SCHEMA, SCHEMA,
        specs=[TablePairSpec(source_table="payments_src", target_table="payments_gold",
                             join_keys=["payment_id"])],
        recon_schema=RECON_SCHEMA,
    )
    for p in res.pairs:
        print(f"  {p.source_table} -> {p.target_table}: status={p.status} "
              f"mismatch_cols={p.mismatch_columns} missing_in_target={p.missing_in_target}")
    print(f"[recon] recon_id = {res.recon_id}")
    return res.recon_id


def build_mapping():
    import yaml

    from rca_engine.lakebridge import build_mapping as _bm
    manifest = yaml.safe_load(open(os.path.join(REPO, MANIFEST)))
    tables = manifest.get("tables", manifest)
    return _bm(None, None, None, source_scripts=None, source_dialect="snowflake",
               table_manifest=tables)


def ask_claude(w, endpoint: str, bundle: dict):
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

    # Note: newer Claude reasoning endpoints reject `temperature`; omit it. The reasoning
    # trace consumes output tokens before the answer, so give a generous max_tokens.
    resp = w.serving_endpoints.query(
        name=endpoint,
        messages=[
            ChatMessage(role=ChatMessageRole.SYSTEM, content=_SYSTEM),
            ChatMessage(role=ChatMessageRole.USER,
                        content="Finding to resolve (JSON):\n" + json.dumps(bundle, default=str)),
        ],
        max_tokens=4000,
    )
    choices = getattr(resp, "choices", None) or []
    if not choices:
        return None
    content = choices[0].message.content if choices[0].message else None
    # Claude reasoning endpoints return content as a list of blocks: a `reasoning`
    # block (skip it) followed by the answer `text` block(s).
    if isinstance(content, list):
        parts = []
        for b in content:
            btype = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
            if btype and btype != "text":
                continue
            if isinstance(b, dict):
                parts.append(b.get("text") or "")
            else:
                parts.append(getattr(b, "text", "") or "")
        content = "".join(parts)
    return _extract_json(content or "")


def llm_fallback(result, runner, mapping, profile: str, endpoint: str) -> int:
    from databricks.sdk import WorkspaceClient

    from rca_engine.resolve import build_evidence_bundle, resolve_finding, unresolved_findings

    residuals = unresolved_findings(result)
    if not residuals:
        print("[llm] no residual findings — deterministic pass concluded everything.")
        return 0
    print(f"[llm] {len(residuals)} residual finding(s) -> asking {endpoint} ...")
    w = WorkspaceClient(profile=profile)
    promoted = 0
    for f in residuals:
        bundle = build_evidence_bundle(f, mapping=mapping, dialect="snowflake", runner=runner)
        proposal = ask_claude(w, endpoint, bundle)
        print(f"  [{f.column}] proposal = {json.dumps(proposal) if proposal else None}")
        if not proposal or not proposal.get("resolvable"):
            continue
        cq = proposal.get("confirm_query")
        cat = proposal.get("category")
        if not cq or not cat:
            continue
        ok = resolve_finding(
            f, runner, category=cat, verdict=proposal.get("verdict"),
            rationale=(proposal.get("rationale") or "LLM fallback hypothesis")[:2000],
            confirm_query=cq,
        )
        print(f"  [{f.column}] confirming query {'CONFIRMED -> promoted' if ok else 'did NOT confirm'}")
        if ok:
            promoted += 1
    return promoted


def summarize(result) -> None:
    print("\n" + "=" * 78)
    print("FINDINGS SUMMARY")
    print("=" * 78)
    for f in result.findings:
        top = f.top_hypothesis
        cat = top.category.value if top else "-"
        verdict = top.verdict.value if top else "-"
        tier = f.metadata.get("llm_fallback")
        tier_lbl = {"confirmed": "TIER 2 (LLM confirmed)",
                    "not_confirmed": "TIER 2 (LLM not confirmed)",
                    "query_failed": "TIER 2 (LLM query failed)"}.get(tier, "TIER 1 (deterministic)")
        print(f"  {f.target_table.split('.')[-1]}.{f.column or '(rows)'}: "
              f"{cat} / {verdict}  [{tier_lbl}]  mismatches={f.mismatch_count}/{f.total_count}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="ps-dr-east")
    ap.add_argument("--warehouse-id", default="4c79c6902dd2bbc2")
    ap.add_argument("--endpoint", default="databricks-claude-opus-5")
    ap.add_argument("--skip-deploy", action="store_true")
    ap.add_argument("--recon-id", default=None, help="Reuse an existing recon_id (skip recon).")
    args = ap.parse_args(argv)

    from rca_engine.analyze import analyze
    from rca_engine.runners import StatementRunner

    runner = StatementRunner(warehouse_id=args.warehouse_id, profile=args.profile)

    if not args.skip_deploy:
        deploy(runner)
    recon_id = args.recon_id or reconcile(runner)

    mapping = build_mapping()
    print("[rca] running deterministic analysis (probes + drill-down + lineage + code-aware) ...")
    result = analyze(runner, recon_id, CATALOG, RECON_SCHEMA,
                     dialect="snowflake", drilldown=True, mapping=mapping,
                     use_lineage=True, max_lineage_hops=10)

    print("\n[rca] deterministic verdicts:")
    summarize(result)

    promoted = llm_fallback(result, runner, mapping, args.profile, args.endpoint)
    print(f"\n[llm] promoted {promoted} residual finding(s) via the confirming-query gate.")

    print("\n[rca] FINAL verdicts (after LLM fallback):")
    summarize(result)
    print(f"\nrecon_id = {recon_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
