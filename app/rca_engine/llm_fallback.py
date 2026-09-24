"""Engine-side Tier-2 LLM fallback via a Databricks Foundation Model endpoint.

This is the headless counterpart to what the Genie Code skill does interactively:
for each residual (``needs_review`` / ``unknown``) finding the deterministic pass
could not conclude, ask a Foundation Model serving endpoint to propose a root-cause
category and a **confirming SQL query**, then let :func:`rca_engine.resolve.resolve_finding`
run that query and promote the verdict **only if it confirms**. The model widens
coverage on the long tail; it never sets a verdict on opinion — the query is the gate.

Used by the CLI when ``--endpoint`` is supplied. Everything is best-effort: a missing
endpoint, malformed JSON, or a failing proposed query leaves the finding as
``needs_review`` and the run proceeds unaffected.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from rca_engine.ingest import QueryRunner
from rca_engine.models import RcaResult, RootCauseCategory
from rca_engine.resolve import build_evidence_bundle, needs_query, resolve_finding

_SYSTEM = (
    "You are a migration reconciliation root-cause analyst. A deterministic engine has "
    "already classified the known mismatch mechanisms; you only see the residual findings "
    "it could not conclude. For ONE finding, propose the single most likely root-cause "
    "category and a SQL query that would CONFIRM it against the real source/target tables. "
    "You must not guess a verdict — the query is what proves it.\n\n"
    "Rules:\n"
    "- Use the fully-qualified table names given (source_table, target_table).\n"
    "- The query MUST return EXACTLY two columns: `confirmed` (a single boolean) and `n`\n"
    "  (bigint count of joined rows). Return NO other columns. `confirmed` MUST be TRUE\n"
    "  exactly when your hypothesis holds, FALSE otherwise. Keep it aggregate — never dump rows.\n"
    "- CONFIRM by reconstructing the TARGET column and asserting it matches on every joined row.\n"
    "  The `target_derivation` field (when present) is the migrated expression that produced the\n"
    "  column: rewrite it over the SOURCE base columns (join source s to target t on the key) and\n"
    "  assert `count_if(NOT (t.<col> <=> <target_derivation over s.*>)) = 0 AS confirmed`. This\n"
    "  proves the migrated formula IS the cause. Do NOT also require the source column to match\n"
    "  any 'correct' formula — that is not what you are testing.\n"
    "- Use the SOURCE base input columns (quantity, unit_price, discount_pct, tax_rate, raw\n"
    "  status/name columns, ...) for the reconstruction — a same-named TARGET column may itself\n"
    "  be independently transformed, so prefer s.* inputs.\n"
    "- For DECIMAL/DOUBLE columns compare with a tolerance that ABSORBS last-digit\n"
    "  DECIMAL-vs-DOUBLE rounding noise — you are proving the formula STRUCTURE, not the last\n"
    "  digit. Use ~0.01 for money/amount columns (never 1e-6):\n"
    "  `count_if(abs(cast(t.<col> AS double) - (<derivation over s.*>)) > 0.01) = 0 AS confirmed`.\n"
    "  A wrong formula misses by orders of magnitude more than the tolerance, so this stays safe.\n"
    "- If the `target_derivation` references a join alias (e.g. an FX/rate/lookup table), the\n"
    "  `join_context` field gives the exact FROM/JOIN clause and the referenced tables' real\n"
    "  column names — use them to reconstruct the joined value (join the same lookup on the\n"
    "  same keys). Only if `join_context` is ABSENT and you'd have to guess a table's columns,\n"
    "  set resolvable=false. A join grain/key difference (e.g. joining on month-start instead of\n"
    "  the daily date) is category=transpilation, verdict=migration_induced.\n"
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
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _flatten_content(content: Any) -> str:
    """Claude reasoning endpoints return content as a list of blocks: a `reasoning`
    block (skip it) followed by the answer `text` block(s). Older endpoints return a
    plain string. Normalize both to a single string."""
    if isinstance(content, str) or content is None:
        return content or ""
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            btype = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
            if btype and btype != "text":
                continue
            parts.append((b.get("text") if isinstance(b, dict) else getattr(b, "text", "")) or "")
        return "".join(parts)
    return str(content)


def _build_client(profile: str | None):
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def _ask_model(client, endpoint: str, bundle: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Query the Foundation Model serving endpoint; return the parsed proposal or None.

    Note: newer Claude reasoning endpoints reject ``temperature`` and consume output
    tokens on the reasoning trace before the answer, so we omit ``temperature`` and use
    a generous ``max_tokens``.
    """
    try:
        from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

        resp = client.serving_endpoints.query(
            name=endpoint,
            messages=[
                ChatMessage(role=ChatMessageRole.SYSTEM, content=_SYSTEM),
                ChatMessage(
                    role=ChatMessageRole.USER,
                    content="Finding to resolve (JSON):\n" + json.dumps(bundle, default=str),
                ),
            ],
            max_tokens=4000,
        )
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return None
        content = choices[0].message.content if choices[0].message else None
        return _extract_json(_flatten_content(content))
    except Exception as exc:  # endpoint missing / no access / SDK error
        print(f"[llm_fallback] model query failed: {exc}")
        return None


def run_llm_fallback(
    result: RcaResult,
    runner: QueryRunner,
    endpoint: str,
    dialect: str = "",
    mapping: dict | None = None,
    profile: str | None = None,
    client: Any = None,
    max_findings: int = 25,
    verbose: bool = True,
) -> int:
    """Attempt to resolve residual findings with a Foundation Model endpoint.

    Returns the number of findings promoted to a confirmed verdict. Best-effort — never
    raises. Pass an existing ``client`` (``WorkspaceClient``) or a ``profile`` to build one.
    """
    if not endpoint:
        return 0
    # Match the interactive Genie gate: besides the residual (needs_review / unknown), also
    # refine findings the deterministic pass left WITHOUT an executed confirming query, AND
    # any transform-GENERATED column still tagged with the generic `transpilation` catch-all
    # (the mechanism is a guess like "rounding" — the model can reconstruct the exact
    # migrated derivation and prove which term is wrong). Promotion stays query-gated in
    # resolve_finding, so a wrong hypothesis simply doesn't stick.
    residuals = list(needs_query(result))
    _seen = {id(f) for f in residuals}
    for f in result.findings:
        if id(f) in _seen or f.metadata.get("llm_fallback") == "confirmed":
            continue
        top = f.top_hypothesis
        if top is not None and f.metadata.get("code_generated") \
                and top.category == RootCauseCategory.TRANSPILATION:
            residuals.append(f)
            _seen.add(id(f))
    if not residuals:
        if verbose:
            print("[llm_fallback] nothing to refine — deterministic pass concluded + confirmed everything.")
        return 0
    try:
        client = client or _build_client(profile)
    except Exception as exc:
        print(f"[llm_fallback] could not build workspace client: {exc}")
        return 0

    if verbose:
        print(f"[llm_fallback] {len(residuals)} residual finding(s) -> asking {endpoint} ...")
    promoted = 0
    for f in residuals[:max_findings]:
        try:
            bundle = build_evidence_bundle(f, mapping=mapping, dialect=dialect, runner=runner)
            proposal = _ask_model(client, endpoint, bundle)
            tag = f"{f.target_table.split('.')[-1]}.{f.column or '(rows)'}"
            if not proposal or not proposal.get("resolvable"):
                if verbose:
                    print(f"  [{tag}] no resolvable hypothesis")
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
                # a reconstruction that matches every row is strong proof — rank it above
                # the deterministic guess (which can also sit at 0.85) so it becomes top.
                confidence=0.95,
            )
            if verbose:
                print(f"  [{tag}] confirming query {'CONFIRMED -> promoted' if ok else 'did NOT confirm'}")
            if ok:
                promoted += 1
        except Exception as exc:  # isolate each finding
            print(f"[llm_fallback] finding resolve failed: {exc}")
            continue
    return promoted
