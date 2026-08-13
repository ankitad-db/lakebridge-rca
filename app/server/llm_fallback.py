"""App-side Tier-2 LLM fallback via the Databricks Foundation Model API.

Mirrors what the Genie Code skill does interactively, but headless: for each
residual (``needs_review`` / ``unknown``) finding, ask a Foundation Model serving
endpoint to propose a root-cause category and a **confirming SQL query**, then let
``rca_engine.resolve.resolve_finding`` run that query and promote the verdict **only
if it confirms**. The model widens coverage on the long tail; it never sets a
verdict on opinion — the query is the gate.

Everything is best-effort: if the endpoint is unavailable, returns malformed JSON,
or a proposed query fails, the finding is left as ``needs_review`` and the run
proceeds unaffected.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from rca_engine.ingest import QueryRunner
from rca_engine.models import RcaResult
from rca_engine.resolve import build_evidence_bundle, resolve_finding, unresolved_findings

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


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    # Strip markdown fences / prose around the JSON object.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _ask_model(endpoint: str, bundle: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Query the Foundation Model serving endpoint; return the parsed proposal or None."""
    try:
        from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

        from .config import get_workspace_client

        w = get_workspace_client()
        resp = w.serving_endpoints.query(
            name=endpoint,
            messages=[
                ChatMessage(role=ChatMessageRole.SYSTEM, content=_SYSTEM),
                ChatMessage(
                    role=ChatMessageRole.USER,
                    content="Finding to resolve (JSON):\n" + json.dumps(bundle, default=str),
                ),
            ],
            temperature=0.0,
            max_tokens=700,
        )
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return None
        content = choices[0].message.content if choices[0].message else None
        return _extract_json(content or "")
    except Exception as exc:  # endpoint missing / no access / SDK error
        print(f"[llm_fallback] model query failed: {exc}")
        return None


def run_llm_fallback(
    result: RcaResult,
    runner: QueryRunner,
    endpoint: str,
    dialect: str = "",
    mapping: dict | None = None,
    max_findings: int = 25,
) -> int:
    """Attempt to resolve residual findings with the Foundation Model API.

    Returns the number of findings promoted to a confirmed verdict. Best-effort —
    never raises.
    """
    if not endpoint:
        return 0
    residuals = unresolved_findings(result)
    promoted = 0
    for f in residuals[:max_findings]:
        try:
            bundle = build_evidence_bundle(f, mapping=mapping, dialect=dialect, runner=runner)
            proposal = _ask_model(endpoint, bundle)
            if not proposal or not proposal.get("resolvable"):
                continue
            category = proposal.get("category")
            confirm_query = proposal.get("confirm_query")
            if not category or not confirm_query:
                continue
            ok = resolve_finding(
                f, runner,
                category=category,
                verdict=proposal.get("verdict"),
                rationale=(proposal.get("rationale") or "LLM fallback hypothesis")[:2000],
                confirm_query=confirm_query,
            )
            if ok:
                promoted += 1
        except Exception as exc:  # isolate each finding
            print(f"[llm_fallback] finding resolve failed: {exc}")
            continue
    return promoted
