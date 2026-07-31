"""Genie Code synthesis layer — a *grounded narrative* on top of the concluded RCA.

The deterministic engine (probes → classify → drill-down → drift → clusters) decides
every verdict and backs it with an executed query. This module does **not** touch that.
It gives the Genie Code agent two safe things:

- ``build_narrative_context`` — a compact, purely factual view of the *already-concluded*
  result (verdict counts, systemic clusters, per-table findings with their category /
  verdict / confidence / rationale / drift / top evidence). The agent reasons over this
  to write a plain-English "what happened & why".
- ``set_narrative`` — writes that prose back onto the result / per-table summaries so
  ``report.write_rca_bundle`` renders it as a clearly-labeled "Analyst summary" block.

The contract that keeps this trustworthy: the context is read-only facts and the setter
stores *description only*. Neither can change a verdict — determinism + the executed
drill-down query remain the source of truth. Narrative is always labeled as LLM synthesis
so a reader never mistakes it for evidence.
"""

from __future__ import annotations

from typing import Any

from rca_engine.models import RcaResult


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`") if name else name


def _finding_facts(f: Any) -> dict[str, Any]:
    top = f.top_hypothesis
    drift = (f.metadata or {}).get("drift") or {}
    return {
        "location": f"{_short(f.target_table)}.{f.column}" if f.column else _short(f.target_table),
        "column": f.column,
        "recon_type": f.recon_type.value,
        "mismatch_count": f.mismatch_count,
        "total_count": f.total_count,
        "category": top.category.value if top else None,
        "verdict": top.verdict.value if top else None,
        "confidence": top.confidence if top else None,
        "rationale": top.rationale if top else None,
        # Only the drift signal that helps phrase migration-vs-genuine — not the full row.
        "drift": {
            "material": drift.get("material"),
            "null_pp_delta": drift.get("null_pp_delta"),
            "ndv_frac_delta": drift.get("ndv_frac_delta"),
        } if drift else None,
        # A couple of already-executed evidence lines for grounding (facts, not opinion).
        "evidence": [e.detail for e in (top.evidence[:3] if top else [])],
    }


def build_narrative_context(result: RcaResult, max_findings_per_table: int = 8) -> dict[str, Any]:
    """A compact, JSON-serializable, *factual* view of the concluded result for the
    Genie Code agent to write a grounded narrative from. Contains no free space to set
    a verdict — every value here is already decided by the deterministic engine."""

    by_table: dict[str, list[Any]] = {}
    for f in result.findings:
        by_table.setdefault(f.target_table, []).append(f)

    summary_by_table = {s.target_table: s for s in result.table_summaries}
    tables = []
    for tbl in sorted(set(by_table) | set(summary_by_table)):
        s = summary_by_table.get(tbl)
        fs = by_table.get(tbl, [])
        tables.append({
            "target_table": tbl,
            "source_table": _short(fs[0].source_table) if fs else (_short(s.source_table) if s else ""),
            "row_match_pct": s.row_match_pct if s else None,
            "missing_in_target": s.missing_in_target if s else 0,
            "missing_in_source": s.missing_in_source if s else 0,
            "absolute_mismatch": s.absolute_mismatch if s else 0,
            "downstream_count": len(s.downstream_tables) if s else 0,
            "downstream_tables": (s.downstream_tables[:8] if s else []),
            "findings": [_finding_facts(f) for f in fs[:max_findings_per_table]],
            "findings_total": len(fs),
        })

    return {
        "recon_id": result.recon_id,
        "dialect": result.dialect,
        "totals": {"findings": len(result.findings),
                   "tables": len({f.target_table for f in result.findings})},
        "verdict_counts": result.verdict_counts(),
        "clusters": [
            {"signature": c.signature, "category": c.category.value, "verdict": c.verdict.value,
             "finding_count": c.finding_count, "rows_impacted": c.rows_impacted,
             "tables": c.tables, "members": c.members[:8]}
            for c in result.clusters
        ],
        "tables": tables,
    }


def set_narrative(
    result: RcaResult,
    overall: str = "",
    per_table: dict[str, str] | None = None,
) -> RcaResult:
    """Attach grounded prose (description only) to the result.

    ``overall`` becomes the run-level "Analyst summary". ``per_table`` maps a table name
    (full ``catalog.schema.table`` or its short name, case-insensitive) to that table's
    paragraph. Unknown keys are ignored. Returns the same result for chaining, e.g.::

        set_narrative(result, overall=..., per_table={...})
        write_rca_bundle(result, out_dir, recon_id)
    """

    if overall:
        result.narrative = overall.strip()

    if per_table:
        # Index summaries by both full and short name so either key works.
        index: dict[str, Any] = {}
        for s in result.table_summaries:
            index[s.target_table.lower()] = s
            index[_short(s.target_table).lower()] = s
        for key, text in per_table.items():
            s = index.get(str(key).strip().lower())
            if s is not None and text:
                s.narrative = text.strip()
    return result
