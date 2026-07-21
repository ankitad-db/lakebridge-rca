"""Bridges the App to the RCA engine: discover runs, load a bundle, and shape a
UI-friendly view. The App is a *reader/orchestrator* — it renders pre-computed
bundles and (optionally) triggers a live run; it never re-implements engine logic.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from rca_engine.models import Finding, RcaResult, ReconType, TableSummary, Verdict
from rca_engine.severity import severity_label, severity_score

from .config import Settings, get_workspace_client

_VERDICT_META = {
    "migration_induced": {"icon": "🔧", "label": "Migration-induced", "action": "Fix in the migration"},
    "genuine_data": {"icon": "📊", "label": "Genuine data difference", "action": "Route to the data owner"},
    "benign": {"icon": "✅", "label": "Benign / expected", "action": "No action"},
    "needs_review": {"icon": "🔍", "label": "Needs review", "action": "Investigate further"},
}


class SdkStatementRunner:
    """QueryRunner backed by the Databricks SDK Statement Execution API (no CLI)."""

    def __init__(self, warehouse_id: str):
        self._wid = warehouse_id
        self._w = get_workspace_client()

    def query(self, sql: str) -> list[dict[str, Any]]:
        from databricks.sdk.service.sql import StatementState

        resp = self._w.statement_execution.execute_statement(
            warehouse_id=self._wid, statement=sql, wait_timeout="50s"
        )
        # Poll if not finished within the wait window.
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            resp = self._w.statement_execution.get_statement(resp.statement_id)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            msg = getattr(getattr(resp.status, "error", None), "message", resp.status.state if resp.status else "?")
            raise RuntimeError(f"Statement failed: {msg}")
        cols = [c.name for c in resp.manifest.schema.columns] if resp.manifest and resp.manifest.schema else []
        data = (resp.result.data_array if resp.result else None) or []
        return [dict(zip(cols, row)) for row in data]


def _runner(settings: Settings):
    return SdkStatementRunner(settings.warehouse_id) if settings.has_warehouse else None


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def list_runs(settings: Settings) -> list[dict[str, Any]]:
    """Recent recon runs from the warehouse; falls back to on-disk bundles."""
    runner = _runner(settings)
    if runner is not None and settings.recon_catalog:
        try:
            from rca_engine.discovery import list_recon_runs

            runs = list_recon_runs(runner, settings.recon_catalog, settings.recon_schema)
            known = _bundles_on_disk(settings)
            for r in runs:
                r["has_bundle"] = r["recon_id"] in known
            return runs
        except Exception as exc:  # degrade to bundles rather than 500
            print(f"[rca] live discovery failed, using on-disk bundles: {exc}")
    return _runs_from_bundles(settings)


def _bundles_on_disk(settings: Settings) -> set[str]:
    d = settings.bundles_dir
    if not d or not os.path.isdir(d):
        return set()
    out = set()
    for name in os.listdir(d):
        if name.startswith("rca_") and os.path.isdir(os.path.join(d, name)):
            out.add(name[len("rca_"):])
    return out


def _runs_from_bundles(settings: Settings) -> list[dict[str, Any]]:
    runs = []
    for recon_id in sorted(_bundles_on_disk(settings)):
        result = load_result(settings, recon_id)
        if result is None:
            continue
        with_diffs = sum(
            1 for s in result.table_summaries
            if s.missing_in_source or s.missing_in_target or s.absolute_mismatch or not s.schema_ok
        )
        runs.append({
            "recon_id": recon_id,
            "started": None,
            "ended": None,
            "table_pairs": len(result.table_summaries),
            "tables_with_diffs": with_diffs,
            "clean": with_diffs == 0 and len(result.table_summaries) > 0,
            "has_bundle": True,
        })
    return runs


# --------------------------------------------------------------------------- #
# Load a concluded result (from a saved bundle, or run live if allowed)
# --------------------------------------------------------------------------- #
def _bundle_json_path(settings: Settings, recon_id: str) -> str:
    return os.path.join(settings.bundles_dir, f"rca_{recon_id}", f"rca_{recon_id}.json")


def load_result(settings: Settings, recon_id: str) -> Optional[RcaResult]:
    path = _bundle_json_path(settings, recon_id)
    if os.path.exists(path):
        with open(path) as f:
            return _result_from_dict(json.load(f))
    if settings.allow_ondemand and settings.has_warehouse and settings.recon_catalog:
        from rca_engine.analyze import analyze

        return analyze(_runner(settings), recon_id, settings.recon_catalog,
                       settings.recon_schema, dialect=settings.dialect, drilldown=True)
    return None


def summary_md(settings: Settings, recon_id: str) -> Optional[str]:
    path = os.path.join(settings.bundles_dir, f"rca_{recon_id}", "SUMMARY.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    result = load_result(settings, recon_id)
    if result is None:
        return None
    from rca_engine.report import build_summary_md

    return build_summary_md(result)


def _result_from_dict(d: dict[str, Any]) -> RcaResult:
    """Reconstruct enough of RcaResult from the saved JSON to compute the view."""
    from rca_engine.models import Evidence, Hypothesis, MismatchSample, RootCauseCategory

    def _finding(fd: dict) -> Finding:
        f = Finding(
            recon_id=fd.get("recon_id", ""),
            source_table=fd.get("source_table", ""),
            target_table=fd.get("target_table", ""),
            recon_type=ReconType(fd.get("recon_type", "column_mismatch")),
            column=fd.get("column"),
            mismatch_count=fd.get("mismatch_count", 0) or 0,
            total_count=fd.get("total_count", 0) or 0,
            samples=[MismatchSample(**{k: s.get(k) for k in ("keys", "column", "source_value", "target_value")})
                     for s in (fd.get("samples") or [])],
            metadata=fd.get("metadata", {}) or {},
        )
        for hd in fd.get("hypotheses") or []:
            f.hypotheses.append(Hypothesis(
                category=RootCauseCategory(hd.get("category", "unknown")),
                verdict=Verdict(hd.get("verdict", "needs_review")),
                confidence=hd.get("confidence", 0.0) or 0.0,
                rationale=hd.get("rationale", ""),
                remediation=hd.get("remediation", ""),
                recommended_owner=hd.get("recommended_owner", ""),
                evidence=[Evidence(label=e.get("label", ""), detail=e.get("detail", ""),
                                   query=e.get("query"), data=e.get("data"))
                          for e in (hd.get("evidence") or [])],
            ))
        return f

    summaries = [TableSummary(**{k: s.get(k) for k in (
        "source_table", "target_table", "source_count", "target_count", "missing_in_source",
        "missing_in_target", "absolute_mismatch", "mismatch_columns", "schema_ok",
        "join_keys", "date_column") if k in s}) for s in (d.get("table_summaries") or [])]
    return RcaResult(
        recon_id=d.get("recon_id", ""),
        dialect=d.get("dialect", "snowflake"),
        findings=[_finding(fd) for fd in (d.get("findings") or [])],
        table_summaries=summaries,
    )


# --------------------------------------------------------------------------- #
# UI view (structured, so the frontend stays dumb)
# --------------------------------------------------------------------------- #
def _short(t: str) -> str:
    return t.split(".")[-1] if t else t


def _finding_view(f: Finding) -> dict[str, Any]:
    h = f.top_hypothesis
    loc = _short(f.target_table) + (f".{f.column}" if f.column else "")
    confirmed = bool(h and any((e.data or {}).get("confirmed") for e in h.evidence if isinstance(e.data, dict)))
    return {
        "location": loc,
        "table": _short(f.target_table),
        "column": f.column,
        "recon_type": f.recon_type.value,
        "mismatch_count": f.mismatch_count,
        "total_count": f.total_count,
        "match_pct": (round(100.0 * (f.total_count - f.mismatch_count) / f.total_count, 2)
                      if f.total_count else None),
        "category": h.category.value if h else None,
        "verdict": h.verdict.value if h else "needs_review",
        "confidence": round(h.confidence, 2) if h else 0.0,
        "confirmed": confirmed,
        "severity": severity_label(f),
        "severity_score": severity_score(f),
        "rationale": h.rationale if h else "",
        "remediation": h.remediation if h else "",
        "owner": h.recommended_owner if h else "",
        "evidence": [{"label": e.label, "detail": e.detail, "query": e.query}
                     for e in (h.evidence if h else [])],
        "samples": [{"keys": s.keys, "source": s.source_value, "target": s.target_value}
                    for s in f.samples[:8]],
    }


def build_view(result: RcaResult) -> dict[str, Any]:
    findings = sorted(result.findings, key=severity_score, reverse=True)
    fviews = [_finding_view(f) for f in findings]

    tables = []
    by_target = {}
    for f in result.findings:
        by_target.setdefault(_short(f.target_table), []).append(f)
    for s in result.table_summaries:
        name = _short(s.target_table)
        fs = by_target.get(name, [])
        vcount: dict[str, int] = {}
        for f in fs:
            if f.top_hypothesis:
                vcount[f.top_hypothesis.verdict.value] = vcount.get(f.top_hypothesis.verdict.value, 0) + 1
        worst = max((severity_score(f) for f in fs), default=-1)
        tables.append({
            "name": name,
            "source_table": s.source_table,
            "target_table": s.target_table,
            "source_count": s.source_count,
            "target_count": s.target_count,
            "missing_in_target": s.missing_in_target,
            "missing_in_source": s.missing_in_source,
            "absolute_mismatch": s.absolute_mismatch,
            "row_match_pct": s.row_match_pct,
            "schema_ok": s.schema_ok,
            "findings_count": len(fs),
            "verdicts": vcount,
            "max_severity": (severity_label(max(fs, key=severity_score)) if fs else None),
            "max_severity_score": worst,
            "clean": len(fs) == 0,
        })
    tables.sort(key=lambda t: t["max_severity_score"], reverse=True)

    total_src = sum(s.source_count for s in result.table_summaries)
    matched = sum(s.matched_rows for s in result.table_summaries)
    overall_row_match = round(100.0 * matched / total_src, 2) if total_src else 100.0

    top = [fv for fv in fviews if fv["verdict"] != "benign"][:5]

    return {
        "recon_id": result.recon_id,
        "dialect": result.dialect,
        "verdict_counts": result.verdict_counts(),
        "verdict_meta": _VERDICT_META,
        "overall_row_match_pct": overall_row_match,
        "table_pairs": len(result.table_summaries),
        "findings_total": len(result.findings),
        "top_priorities": top,
        "tables": tables,
        "findings": fviews,
    }
