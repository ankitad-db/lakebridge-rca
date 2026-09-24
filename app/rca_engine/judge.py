"""LLM-as-judge: an OFFLINE quality grader for RCA output.

This is an *evaluation* tool, not part of the runtime RCA — it never changes a verdict.
Given a concluded :class:`~rca_engine.models.RcaResult` (and optionally a ground-truth
``oracle``), it grades each finding on:

* ``verdict_correct``        — did the verdict match the oracle? (only when an oracle is given)
* ``evidence_sufficiency``   — 0-1, is the finding backed by enough independent evidence?
* ``fix_validity``           — 0-1, is the attached fix concrete/validated?
* ``narrative_faithfulness`` — 0-1, is the rationale grounded (not hand-wavy)?

…plus a run-level summary (verdict precision/recall vs the oracle, mean scores). It powers
benchmarking / regression scoring (see the ``rca-eval`` skill).

Two backends, auto-selected:

* **LLM grader** — when an ``endpoint`` (a Databricks Foundation Model serving endpoint)
  is available, ask the model to grade each finding (reusing the same
  ``WorkspaceClient.serving_endpoints`` path as :mod:`rca_engine.llm_fallback`).
* **Deterministic grader** — otherwise (and in tests), grade from structure alone:
  verdict-vs-oracle, evidence count/kinds, and ``fix.validated``. Always works offline.

The oracle is a mapping ``{"table.column" (or "table"): "<verdict value>"}`` — e.g.
``{"fact_sales.amount": "migration_induced"}``.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from rca_engine.models import Finding, RcaResult, Verdict

# Evidence labels that represent an *independent* confirmation source (not just a probe).
_STRONG_EVIDENCE = {"drilldown", "llm_drilldown", "lineage", "code", "source_trace",
                    "drift", "transpile", "aggregate"}


def _loc(f: Finding) -> str:
    tbl = (f.target_table or "").split(".")[-1]
    return f"{tbl}.{f.column}" if f.column else tbl


def _oracle_verdict(oracle: dict[str, str] | None, f: Finding) -> Optional[str]:
    if not oracle:
        return None
    loc = _loc(f)
    tbl = (f.target_table or "").split(".")[-1]
    for key in (loc, loc.lower(), tbl, tbl.lower()):
        if key in oracle:
            return str(oracle[key])
    return None


# --------------------------------------------------------------------------- #
# Deterministic grader (structure-only; always available)
# --------------------------------------------------------------------------- #
def _grade_finding_deterministic(f: Finding, oracle: dict[str, str] | None) -> dict[str, Any]:
    h = f.top_hypothesis
    evidence = h.evidence if h else []
    strong = [e for e in evidence if e.label in _STRONG_EVIDENCE]
    queried = [e for e in evidence if getattr(e, "query", None)]

    # evidence_sufficiency: reward independent sources + an executed query.
    suff = min(1.0, 0.25 * len(strong) + (0.25 if queried else 0.0))
    if h is None:
        suff = 0.0

    # fix_validity: validated fix = 1.0, suggested = 0.4, none = 0.0.
    fix = getattr(h, "fix", None) if h else None
    fix_validity = 1.0 if (fix and fix.validated) else (0.4 if fix else 0.0)

    # narrative_faithfulness: grounded if the rationale is specific and evidence exists.
    rationale = (h.rationale if h else "") or ""
    narr = 0.0
    if rationale:
        narr = 0.5 + (0.3 if strong else 0.0) + (0.2 if len(rationale) > 60 else 0.0)
        narr = min(1.0, narr)

    exp = _oracle_verdict(oracle, f)
    got = h.verdict.value if h else None
    verdict_correct = (exp == got) if exp is not None else None

    return {
        "location": _loc(f),
        "verdict": got,
        "expected_verdict": exp,
        "verdict_correct": verdict_correct,
        "evidence_sufficiency": round(suff, 2),
        "fix_validity": round(fix_validity, 2),
        "narrative_faithfulness": round(narr, 2),
        "notes": "deterministic grade (no LLM endpoint)",
    }


# --------------------------------------------------------------------------- #
# LLM grader (Foundation Model endpoint)
# --------------------------------------------------------------------------- #
_SYSTEM = (
    "You are a strict evaluator of automated root-cause analyses for data-migration "
    "reconciliation. Grade ONE finding's QUALITY. Respond with ONLY a JSON object: "
    '{"evidence_sufficiency": <0-1>, "fix_validity": <0-1>, '
    '"narrative_faithfulness": <0-1>, "notes": "<one sentence>"}. '
    "evidence_sufficiency: is the verdict backed by enough independent, query-confirmed "
    "evidence? fix_validity: is the suggested fix concrete and likely correct (validated)? "
    "narrative_faithfulness: is the rationale specific and grounded in the evidence, not "
    "generic? Be conservative; reward query-backed evidence."
)


def _build_client(profile: str | None):
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def _flatten_content(content: Any) -> str:
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


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    import re
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _finding_bundle(f: Finding) -> dict[str, Any]:
    h = f.top_hypothesis
    return {
        "location": _loc(f),
        "recon_type": f.recon_type.value,
        "verdict": h.verdict.value if h else None,
        "category": h.category.value if h else None,
        "rationale": h.rationale if h else "",
        "evidence": [{"label": e.label, "detail": e.detail, "has_query": bool(getattr(e, "query", None))}
                     for e in (h.evidence if h else [])],
        "fix": ({"title": h.fix.title, "validated": h.fix.validated} if (h and h.fix) else None),
    }


def _grade_finding_llm(client, endpoint: str, f: Finding, oracle: dict[str, str] | None) -> Optional[dict[str, Any]]:
    try:
        from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

        resp = client.serving_endpoints.query(
            name=endpoint,
            messages=[
                ChatMessage(role=ChatMessageRole.SYSTEM, content=_SYSTEM),
                ChatMessage(role=ChatMessageRole.USER,
                            content="Finding (JSON):\n" + json.dumps(_finding_bundle(f), default=str)),
            ],
            max_tokens=1500,
        )
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return None
        content = choices[0].message.content if choices[0].message else None
        graded = _extract_json(_flatten_content(content))
        if graded is None:
            return None
    except Exception as exc:  # endpoint missing / no access / SDK error
        print(f"[judge] model query failed: {exc}")
        return None

    h = f.top_hypothesis
    exp = _oracle_verdict(oracle, f)
    got = h.verdict.value if h else None

    def _score(k: str) -> float:
        try:
            return max(0.0, min(1.0, float(graded.get(k))))
        except (TypeError, ValueError):
            return 0.0

    return {
        "location": _loc(f),
        "verdict": got,
        "expected_verdict": exp,
        "verdict_correct": (exp == got) if exp is not None else None,
        "evidence_sufficiency": round(_score("evidence_sufficiency"), 2),
        "fix_validity": round(_score("fix_validity"), 2),
        "narrative_faithfulness": round(_score("narrative_faithfulness"), 2),
        "notes": str(graded.get("notes") or "")[:300],
    }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def _verdict_prf(per_finding: list[dict[str, Any]]) -> dict[str, Any]:
    """Verdict precision/recall/accuracy vs the oracle, over findings that have an
    expected verdict. 'Correct' = predicted verdict equals expected."""
    graded = [p for p in per_finding if p.get("expected_verdict") is not None]
    if not graded:
        return {"graded_findings": 0}
    correct = sum(1 for p in graded if p.get("verdict_correct"))
    total = len(graded)
    # Treat MIGRATION_INDUCED as the "positive" actionable class for P/R.
    pos = Verdict.MIGRATION_INDUCED.value
    tp = sum(1 for p in graded if p["verdict"] == pos and p["expected_verdict"] == pos)
    fp = sum(1 for p in graded if p["verdict"] == pos and p["expected_verdict"] != pos)
    fn = sum(1 for p in graded if p["verdict"] != pos and p["expected_verdict"] == pos)
    precision = round(tp / (tp + fp), 3) if (tp + fp) else None
    recall = round(tp / (tp + fn), 3) if (tp + fn) else None
    return {
        "graded_findings": total,
        "verdict_accuracy": round(correct / total, 3),
        "migration_induced_precision": precision,
        "migration_induced_recall": recall,
    }


def grade_result(
    result: RcaResult | Iterable[Finding],
    oracle: dict[str, str] | None = None,
    endpoint: str | None = None,
    profile: str | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Grade an RCA result's quality. Uses the LLM grader when ``endpoint`` (or ``client``)
    is available, else a deterministic structure-only grader. Never raises for grading
    purposes — a per-finding LLM failure falls back to the deterministic grade."""

    findings = result.findings if isinstance(result, RcaResult) else list(result)

    use_llm = bool(endpoint)
    if use_llm and client is None:
        try:
            client = _build_client(profile)
        except Exception as exc:
            print(f"[judge] could not build client ({exc}); using deterministic grader.")
            use_llm = False

    per_finding: list[dict[str, Any]] = []
    for f in findings:
        graded = None
        if use_llm:
            graded = _grade_finding_llm(client, endpoint, f, oracle)
        if graded is None:
            graded = _grade_finding_deterministic(f, oracle)
        per_finding.append(graded)

    summary = {
        "findings": len(per_finding),
        "backend": "llm" if use_llm else "deterministic",
        "mean_evidence_sufficiency": _mean([p["evidence_sufficiency"] for p in per_finding]),
        "mean_fix_validity": _mean([p["fix_validity"] for p in per_finding]),
        "mean_narrative_faithfulness": _mean([p["narrative_faithfulness"] for p in per_finding]),
    }
    summary.update(_verdict_prf(per_finding))
    return {"summary": summary, "findings": per_finding}
