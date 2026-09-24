"""Tier 2 — LLM (Genie Code) fallback for the residual long tail.

The deterministic pass (probes -> classify -> templated drill-down) resolves the
*known* mismatch mechanisms. Whatever it cannot explain is left as
``NEEDS_REVIEW`` / ``UNKNOWN``. This module is the bridge that lets the Genie Code
skill reason over just those residuals — **without** letting the model set a
verdict on opinion alone.

The contract, and the reason this stays "evidence-first, not an LLM guess":

1. ``unresolved_findings`` surfaces only the residual findings.
2. ``build_evidence_bundle`` packages the facts the model needs (samples, declared
   source type, transpiled target derivation, transpile issues, KB dialect).
3. The Genie Code skill proposes a *category*, a *rationale*, and a **confirming
   SQL query** for each residual.
4. ``resolve_finding`` **executes that query** and promotes the verdict **only if
   the query confirms it**. If it cannot confirm, the finding stays
   ``NEEDS_REVIEW`` with the model's suggestion recorded as the next check.

So the engine remains LLM-free and deterministic; the LLM only widens *coverage*,
never bypasses the "every verdict cites an executed query" guarantee.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from rca_engine.ingest import QueryRunner
from rca_engine.models import (
    Evidence,
    Finding,
    Fix,
    Hypothesis,
    RcaResult,
    RootCauseCategory,
    Verdict,
)

# Categories whose default verdict is "the migration produced this".
_MIGRATION = {
    RootCauseCategory.TYPE_PRECISION,
    RootCauseCategory.TIMEZONE,
    RootCauseCategory.TRANSPILATION,
    RootCauseCategory.VOLUME_MISSING,
    RootCauseCategory.VOLUME_EXTRA,
    RootCauseCategory.NULL_BOOLEAN,
    RootCauseCategory.STRING_FORMAT,
    RootCauseCategory.ENV_CONFIG,
}
_GENUINE = {RootCauseCategory.UPSTREAM_DRIFT}
_BENIGN = {RootCauseCategory.SEMI_STRUCTURED}


def unresolved_findings(source: RcaResult | Iterable[Finding]) -> list[Finding]:
    """Return the residual findings the deterministic pass could not conclude.

    A finding is "unresolved" when it has no hypothesis, or its top hypothesis is
    ``NEEDS_REVIEW`` or ``UNKNOWN`` — exactly the cases the Genie Code fallback
    should reason about."""

    findings = source.findings if isinstance(source, RcaResult) else list(source)
    out: list[Finding] = []
    for f in findings:
        top = f.top_hypothesis
        if top is None or top.verdict == Verdict.NEEDS_REVIEW or top.category == RootCauseCategory.UNKNOWN:
            out.append(f)
    return out


def needs_query(source: RcaResult | Iterable[Finding]) -> list[Finding]:
    """Findings that would benefit from an agent-generated drill-down query.

    Broader than ``unresolved_findings``: besides the residual (``NEEDS_REVIEW`` /
    ``UNKNOWN``), it also returns findings that have **no executed confirming query**
    yet — i.e. the deterministic pass fell back to a generic template (or none). The
    Genie Code agent proposes a targeted query for each and runs it through
    ``resolve_finding``, which only promotes on confirmation. Findings already backed
    by a deterministic drill-down query are left alone."""

    findings = source.findings if isinstance(source, RcaResult) else list(source)
    out: list[Finding] = []
    for f in findings:
        top = f.top_hypothesis
        if top is None:
            out.append(f)
            continue
        has_confirming_query = any(
            e.label in ("drilldown", "llm_drilldown") and e.query for e in top.evidence
        )
        if (not has_confirming_query
                or top.verdict == Verdict.NEEDS_REVIEW
                or top.category == RootCauseCategory.UNKNOWN):
            out.append(f)
    return out


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`").lower() if name else ""


_QUALIFIED_TABLE_RE = re.compile(r"\b([A-Za-z_][\w]*\.[A-Za-z_][\w]*\.[A-Za-z_][\w]*)\b")


def _joins_other_tables(tm) -> bool:
    """True if the target FROM/JOIN references a table other than the source (a lookup)."""
    fs = (tm.from_sql or "").lower()
    return " join " in fs


def _referenced_table_columns(from_sql: str, target_table: str, runner) -> dict[str, list[str]]:
    """Column names of each fully-qualified table referenced in the FROM/JOIN (except the
    target), via information_schema — so the model can reconstruct a joined derivation."""
    out: dict[str, list[str]] = {}
    tgt = target_table.strip("`").lower()
    seen = set()
    for m in _QUALIFIED_TABLE_RE.finditer(from_sql or ""):
        fq = m.group(1)
        if fq.lower() == tgt or fq.lower() in seen:
            continue
        seen.add(fq.lower())
        cat, sch, tbl = fq.split(".")
        try:
            rows = runner.query(
                f"SELECT column_name FROM {cat}.information_schema.columns "
                f"WHERE table_schema='{sch}' AND table_name='{tbl}' ORDER BY ordinal_position"
            )
            cols = [r.get("column_name") for r in rows if r.get("column_name")]
            if cols:
                out[fq] = cols
        except Exception:
            continue
    return out


def build_evidence_bundle(
    finding: Finding,
    mapping: dict | None = None,
    dialect: str = "",
    max_samples: int = 10,
    runner: QueryRunner | None = None,
    lookback_days: int = 90,
) -> dict[str, Any]:
    """Compact, JSON-serializable context for the Genie Code fallback to reason over.

    Includes only facts (no interpretation): the sampled value pairs, the declared
    source type, the transpiled target derivation, transpile warnings, any evidence
    the deterministic passes already gathered (code / transpile / recon_config /
    lineage / drill-down), and — for a true trace-back — Unity Catalog lineage:
    the target column's immediate upstream(s) *and* a depth-agnostic ``trace_back``
    chain walked hop by hop to the root layer, so the model can locate and confirm a
    defect that entered several layers upstream.

    ``runner`` is optional: pass it to fetch UC lineage live (from
    ``system.access.*_lineage``). Lineage already attached by an earlier
    ``use_lineage`` pass is surfaced regardless. Everything is best-effort — a
    failed lineage fetch never breaks the bundle.
    """

    top = finding.top_hypothesis
    bundle: dict[str, Any] = {
        "recon_id": finding.recon_id,
        "source_table": finding.source_table,
        "target_table": finding.target_table,
        "recon_type": finding.recon_type.value,
        "column": finding.column,
        "mismatch_count": finding.mismatch_count,
        "total_count": finding.total_count,
        "dialect": dialect,
        "current_hypothesis": None
        if top is None
        else {
            "category": top.category.value,
            "verdict": top.verdict.value,
            "confidence": top.confidence,
            "rationale": top.rationale,
        },
        "samples": [
            {
                "keys": s.keys,
                "source_value": s.source_value,
                "target_value": s.target_value,
            }
            for s in finding.samples[:max_samples]
        ],
    }

    # Evidence the deterministic passes already gathered (code / transpile /
    # recon_config / lineage / drill-down) — the LLM's starting trace-back context.
    if top is not None and top.evidence:
        bundle["prior_evidence"] = [
            {"label": e.label, "detail": e.detail, "query": e.query}
            for e in top.evidence[:8]
        ]

    tm = (mapping or {}).get(_short(finding.target_table)) if mapping else None
    if tm is not None and finding.column:
        src_type = tm.source_type_of(finding.column)
        ct = tm.transform_for(finding.column)
        bundle["source_type"] = src_type
        bundle["target_derivation"] = (
            None
            if ct is None
            else {"expr": ct.expr, "functions": ct.functions, "is_direct": ct.is_direct}
        )
        bundle["transpile_issues"] = [
            {"severity": i.severity, "kind": i.kind, "message": i.message}
            for i in tm.transpile_issues
        ]
        # If the migrated derivation joins other tables (e.g. an FX/rate/lookup), give the
        # model the FROM/JOIN and those tables' columns so it can reconstruct the value
        # instead of declining. Best-effort: skip silently if the schema fetch fails.
        if ct is not None and not ct.is_direct and tm.from_sql and _joins_other_tables(tm):
            join_ctx: dict[str, Any] = {"from_sql": tm.from_sql}
            if runner is not None:
                cols = _referenced_table_columns(tm.from_sql, finding.target_table, runner)
                if cols:
                    join_ctx["referenced_tables"] = cols
            bundle["join_context"] = join_ctx

    # UC lineage: walk the target column/table back to its upstream(s) so the LLM can
    # locate where the difference entered. Uses already-attached lineage evidence, and
    # optionally a live fetch when a runner is supplied.
    lineage: dict[str, Any] = {}
    attached = [
        e.detail for e in (top.evidence if top else []) if e.label == "lineage"
    ]
    if attached:
        lineage["notes"] = attached
    if runner is not None:
        try:
            from rca_engine.lineage import fetch_lineage, trace_upstream

            info = fetch_lineage(runner, finding.target_table, lookback_days=lookback_days)
            if info.upstream_tables:
                lineage["upstream_tables"] = info.upstream_tables
            if finding.column:
                ups = info.column_upstreams.get(finding.column.lower())
                if ups:
                    lineage["column_upstreams"] = ups
            # Full depth-agnostic trace-back so the model can walk past the first hop and
            # issue a confirming query at whichever upstream layer the difference entered.
            chain = trace_upstream(
                runner, finding.target_table, finding.column or None, lookback_days=lookback_days
            )
            if chain.max_depth >= 2:
                lineage["trace_back"] = {
                    "paths": [
                        [{"table": n.table, "column": n.column} for n in p]
                        for p in chain.paths
                    ],
                    "roots": chain.root_tables(),
                    "max_depth": chain.max_depth,
                    "truncated": chain.truncated,
                }
        except Exception:  # best-effort; lineage is optional
            pass
    if lineage:
        bundle["lineage"] = lineage

    return bundle


def _as_category(category: RootCauseCategory | str) -> RootCauseCategory:
    if isinstance(category, RootCauseCategory):
        return category
    try:
        return RootCauseCategory(str(category).strip().lower())
    except ValueError:
        return RootCauseCategory.UNKNOWN


def _default_verdict(category: RootCauseCategory) -> Verdict:
    if category in _GENUINE:
        return Verdict.GENUINE_DATA
    if category in _BENIGN:
        return Verdict.BENIGN
    if category in _MIGRATION:
        return Verdict.MIGRATION_INDUCED
    return Verdict.NEEDS_REVIEW


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(v)


def _is_confirmed(row: dict[str, Any]) -> bool:
    """Interpret a confirming-query result row.

    Convention: the proposed query should return a boolean ``confirmed`` column.
    We also accept a numeric ``n`` (rows-matching count) as a fallback, and finally
    treat any returned row as weak confirmation."""

    if not row:
        return False
    if "confirmed" in row:
        return _truthy(row["confirmed"])
    if "n" in row:
        try:
            return float(row["n"]) > 0
        except (TypeError, ValueError):
            return False
    return True


def _owner_for(verdict: Verdict) -> str:
    if verdict == Verdict.GENUINE_DATA:
        return "data owner / source team"
    if verdict == Verdict.BENIGN:
        return "no action"
    return "migration engineer"


def resolve_finding(
    finding: Finding,
    runner: QueryRunner,
    *,
    category: RootCauseCategory | str,
    rationale: str,
    confirm_query: str,
    verdict: Verdict | str | None = None,
    remediation: str = "",
    recommended_owner: str = "",
    confidence: float = 0.85,
) -> bool:
    """Test an LLM-proposed hypothesis against real data and finalize only if confirmed.

    Runs ``confirm_query`` (which should return a ``confirmed`` boolean column, and
    ideally an ``n`` count). On confirmation, a new high-confidence hypothesis is
    attached — with the executed query as evidence — and becomes the finding's top
    hypothesis. On non-confirmation (or a failed query), the finding is left as
    ``NEEDS_REVIEW`` and the proposal is recorded as the suggested next check.

    Returns ``True`` iff the finding was promoted to a concluded verdict.
    """

    cat = _as_category(category)
    try:
        rows = runner.query(confirm_query)
        row = rows[0] if rows else {}
        confirmed = _is_confirmed(row)
    except Exception as exc:  # never break the pipeline on a bad proposed query
        finding.metadata["llm_fallback"] = "query_failed"
        top = finding.top_hypothesis
        note = Evidence(
            label="llm_drilldown",
            detail=f"LLM fallback proposed '{cat.value}' but the confirming query failed: {exc}. "
            f"Left as needs-review.",
            query=confirm_query,
        )
        if top is not None:
            top.evidence.append(note)
        return False

    if not confirmed:
        finding.metadata["llm_fallback"] = "not_confirmed"
        top = finding.top_hypothesis
        note = Evidence(
            label="llm_drilldown",
            detail=f"LLM fallback hypothesis '{cat.value}' was NOT confirmed by the query "
            f"(no matching rows). Suggested next check: {rationale}",
            query=confirm_query,
            data=row,
        )
        if top is not None:
            top.evidence.append(note)
        return False

    final_verdict = (
        Verdict(verdict) if isinstance(verdict, str) else verdict
    ) or _default_verdict(cat)
    finding.metadata["llm_fallback"] = "confirmed"
    finding.hypotheses.append(
        Hypothesis(
            category=cat,
            verdict=final_verdict,
            confidence=round(min(0.98, max(0.6, confidence)), 2),
            rationale=rationale,
            remediation=remediation,
            recommended_owner=recommended_owner or _owner_for(final_verdict),
            evidence=[
                Evidence(
                    label="llm_drilldown",
                    detail=f"LLM fallback confirmed '{cat.value}' via a live query.",
                    query=confirm_query,
                    data=row,
                )
            ],
        )
    )
    return True


def set_fix(
    finding: Finding,
    runner: QueryRunner | None = None,
    *,
    title: str,
    sql: str,
    kind: str = "fix_transpile",
    target: str = "transform",
    rationale: str = "",
    confidence: float = 0.7,
    validation_query: str = "",
) -> bool:
    """Attach an LLM (Genie Code) proposed fix to a finding — through the same gate.

    Use this for the cases the deterministic templates can't express well —
    ``transpilation`` (rewrite the mistranslated expression) and ``unknown`` residuals —
    where the agent writes the corrected Databricks SQL grounded in the evidence bundle
    (declared source type, transpiled ``target_derivation``, samples, source scripts).

    The proposal is only marked **validated** when ``validation_query`` runs and confirms
    the corrected SQL closes the gap (a boolean ``confirmed`` column, like the verdict
    gate). Otherwise it is attached as an unvalidated suggestion. Best-effort — a failed
    query never breaks the pipeline. Returns whether the fix was validated.
    """

    top = finding.top_hypothesis
    if top is None:
        return False

    fix = Fix(
        title=title,
        kind=kind,
        sql=sql,
        target=target,
        rationale=rationale,
        confidence=round(min(0.98, max(0.3, confidence)), 2),
        validation_query=validation_query,
    )
    validated = False
    if validation_query and runner is not None:
        try:
            rows = runner.query(validation_query)
            row = rows[0] if rows else {}
            validated = _is_confirmed(row)
            n = row.get("n")
            fix.validated = validated
            fix.validation = (
                "Validated: the corrected SQL closes the gap"
                + (f" ({int(n)} rows checked)" if n is not None else "")
                + "."
                if validated else
                "Not validated: the corrected SQL did not close the gap on the sample; "
                "review before applying."
            )
        except Exception as exc:  # never break the pipeline on a bad validation query
            fix.validation = f"Validation query failed: {exc}"

    top.fix = fix
    top.evidence.append(
        Evidence(
            label="fix",
            detail=f"LLM-proposed fix: {title}"
            + (" (validated by query)" if validated else " (suggested — unvalidated)"),
            query=validation_query or None,
            data={"kind": kind, "target": target, "validated": validated},
        )
    )
    return validated
