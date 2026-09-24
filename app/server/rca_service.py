"""Bridges the App to the RCA engine: discover runs, load a bundle, and shape a
UI-friendly view. The App is a *reader/orchestrator* — it renders pre-computed
bundles and (optionally) triggers a live run; it never re-implements engine logic.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import uuid
from functools import lru_cache
from typing import Any, Optional

from rca_engine.audit import log_audit, read_audit
from rca_engine.models import Finding, RcaResult, ReconType, TableSummary, Verdict
from rca_engine.severity import severity_label, severity_score

from .config import Settings, get_workspace_client, get_workspace_host

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


def _audit_user() -> str:
    """Best-effort identity (service principal in-app, CLI user locally) for the audit trail."""
    try:
        return get_workspace_client().current_user.me().user_name or ""
    except Exception:
        return ""


def _diffs_count(result: RcaResult) -> int:
    return sum(1 for s in result.table_summaries
               if s.missing_in_source or s.missing_in_target or s.absolute_mismatch or not s.schema_ok)


@lru_cache(maxsize=8)
def _build_mapping_cached(transpiled: str, recon_config: str, source_scripts: str, dialect: str):
    if not (transpiled or recon_config or source_scripts):
        return None
    try:
        from rca_engine.lakebridge import build_mapping

        return build_mapping(recon_config or None, transpiled or None, None,
                             source_scripts=source_scripts or None, source_dialect=dialect)
    except Exception as exc:  # code-aware is best-effort; RCA still runs data-only
        print(f"[rca] code-aware mapping skipped: {exc}")
        return None


def _mapping(settings: Settings):
    """Per-column mapping from the migrated SQL artifact so findings carry the
    🔧 Transformation logic + culprit. None when no artifact is configured."""
    return _build_mapping_cached(settings.transpiled_output_dir or "", settings.recon_config_path or "",
                                 settings.source_scripts_dir or "", settings.dialect)


def _maybe_llm_fallback(settings: Settings, result: RcaResult, runner) -> int:
    """Tier-2: resolve residual findings via the Foundation Model API (best-effort).
    Returns the number of findings promoted. No-op unless ``RCA_LLM_FALLBACK`` is on."""
    if not (settings.llm_fallback and settings.llm_endpoint and runner is not None):
        return 0
    try:
        from .llm_fallback import run_llm_fallback

        n = run_llm_fallback(result, runner, settings.llm_endpoint, dialect=settings.dialect,
                             mapping=_mapping(settings))
        if n:
            print(f"[rca] LLM fallback resolved {n} residual finding(s) for {result.recon_id}")
        return n
    except Exception as exc:  # never let the fallback break the run
        print(f"[rca] LLM fallback skipped: {exc}")
        return 0


def list_audit(settings: Settings, limit: int = 50) -> list[dict[str, Any]]:
    """Recent pipeline audit rows (reconcile + RCA history), newest first."""
    runner = _runner(settings)
    if runner is None or not settings.audit_table:
        return []
    rows = read_audit(runner, settings.audit_table, limit=limit)
    for r in rows:
        for k in ("started_ts", "ended_ts"):
            if r.get(k) is not None:
                r[k] = str(r[k])
    return rows


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


def list_dialects(settings: Settings) -> list[str]:
    """Source dialects with a knowledge base (from rca_engine/knowledge/*.yaml). These
    are the Lakebridge-supported sources the RCA has curated semantics for. The
    configured default is floated to the top."""
    import glob

    import rca_engine.knowledge as kb_pkg

    kb_dir = os.path.dirname(os.path.abspath(kb_pkg.__file__))
    found = sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(kb_dir, "*.yaml"))
    )
    default = settings.dialect
    return ([default] if default in found else []) + [d for d in found if d != default] or found


def list_catalogs(settings: Settings) -> list[str]:
    """Catalogs the app identity can see (for the UI catalog picker). Best-effort;
    the configured recon catalog is always included and floated to the top."""
    runner = _runner(settings)
    found: list[str] = []
    if runner is not None:
        try:
            rows = runner.query("SHOW CATALOGS")
            found = [str(r.get("catalog") or r.get("catalog_name") or "")
                     for r in rows]
            found = [c for c in found if c]
        except Exception:
            found = []
    cat = settings.recon_catalog
    ordered = ([cat] if cat else []) + [c for c in sorted(found) if c != cat]
    return ordered or ([cat] if cat else [])


def list_schemas(settings: Settings) -> list[str]:
    """Schemas in the recon catalog (for the trigger-recon form). Best-effort."""
    runner = _runner(settings)
    if runner is None or not settings.recon_catalog:
        return []
    try:
        rows = runner.query(
            f"SELECT schema_name FROM `{settings.recon_catalog}`.information_schema.schemata "
            "ORDER BY schema_name"
        )
        return [str(r.get("schema_name")) for r in rows if r.get("schema_name")]
    except Exception:
        return []


def list_schema_tables(settings: Settings, schema: str) -> list[str]:
    """Table names in a schema of the recon catalog. Best-effort."""
    runner = _runner(settings)
    if runner is None or not settings.recon_catalog or not schema:
        return []
    try:
        safe = schema.replace("'", "''")
        rows = runner.query(
            "SELECT table_name FROM "
            f"`{settings.recon_catalog}`.information_schema.tables "
            f"WHERE table_schema = '{safe}' ORDER BY table_name"
        )
        return [str(r.get("table_name")) for r in rows if r.get("table_name")]
    except Exception:
        return []


def _bundles_on_disk(settings: Settings) -> set[str]:
    d = settings.bundles_dir
    if not d or not os.path.isdir(d):
        return set()
    out = set()
    for name in os.listdir(d):
        if name.startswith("rca_") and os.path.isdir(os.path.join(d, name)):
            out.add(name[len("rca_"):])
    return out


def _bundle_meta(settings: Settings, recon_id: str) -> dict[str, Any]:
    path = os.path.join(settings.bundles_dir, f"rca_{recon_id}", "meta.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _runs_from_bundles(settings: Settings) -> list[dict[str, Any]]:
    runs = []
    for recon_id in _bundles_on_disk(settings):
        result = load_result(settings, recon_id)
        if result is None:
            continue
        meta = _bundle_meta(settings, recon_id)
        with_diffs = sum(
            1 for s in result.table_summaries
            if s.missing_in_source or s.missing_in_target or s.absolute_mismatch or not s.schema_ok
        )
        runs.append({
            "recon_id": recon_id,
            "title": meta.get("title"),
            "source": meta.get("source"),
            "started": meta.get("started"),
            "ended": None,
            "table_pairs": len(result.table_summaries),
            "tables_with_diffs": with_diffs,
            "clean": with_diffs == 0 and len(result.table_summaries) > 0,
            "has_bundle": True,
        })
    runs.sort(key=lambda r: (r["started"] or ""), reverse=True)
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
                       settings.recon_schema, dialect=settings.dialect, drilldown=True,
                       mapping=_mapping(settings), use_lineage=settings.use_lineage,
                       max_lineage_hops=settings.max_lineage_hops)
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


# --------------------------------------------------------------------------- #
# On-demand analysis (one table at a time) — the App's "call the skill" path
# --------------------------------------------------------------------------- #
def list_tables(settings: Settings, recon_id: str) -> list[dict[str, Any]]:
    """Table pairs in a recon run, each flagged with whether it's already analyzed."""
    analyzed = _analyzed_tables(settings, recon_id)
    runner = _runner(settings)
    if runner is not None and settings.recon_catalog:
        from rca_engine.discovery import list_recon_tables

        tables = list_recon_tables(runner, settings.recon_catalog, settings.recon_schema, recon_id)
    else:
        # Demo / no-warehouse: derive the table list from the pre-computed bundle.
        result = load_result(settings, recon_id)
        tables = [] if result is None else [{
            "name": _short(s.target_table), "source_table": s.source_table,
            "target_table": s.target_table,
            "has_diffs": bool(s.missing_in_source or s.missing_in_target
                              or s.absolute_mismatch or not s.schema_ok),
        } for s in result.table_summaries]
    for t in tables:
        t["analyzed"] = t["name"] in analyzed
    return tables


def _analyzed_tables(settings: Settings, recon_id: str) -> set[str]:
    result = load_result(settings, recon_id)
    if result is None:
        return set()
    return {_short(s.target_table) for s in result.table_summaries}


def run_analysis(settings: Settings, recon_id: str, only_table: str) -> RcaResult:
    """Run the RCA (the same engine the Genie skill runs) for a single table.

    Live when a warehouse is configured: ingest -> classify -> live drill-down, then
    merge the result into the recon's bundle (so artifacts + the dashboard update).
    Without a warehouse (demo mode) it replays the pre-computed bundle for that table.
    """
    # Preferred: run the one-table RCA through the Genie Code skill (as a job), then merge
    # the skill-written result into the recon's bundle so the dashboard accumulates tables.
    from .skill_job import run_skill_job, skill_job_ready

    if skill_job_ready(settings):
        import tempfile

        tmp = tempfile.mkdtemp(prefix="rca_skill_")
        status = run_skill_job(settings, mode="rca", recon_id=recon_id,
                               only_table=only_table, fetch_dir=tmp)
        scoped_path = os.path.join(tmp, f"rca_{recon_id}", f"rca_{recon_id}.json")
        if status.get("state") == "done" and os.path.exists(scoped_path):
            with open(scoped_path) as fh:
                scoped = _result_from_dict(json.load(fh))
            _merge_into_bundle(settings, recon_id, scoped)
            return scoped
        print(f"[rca] single-table skill job unavailable ({status.get('message')}); "
              f"falling back to in-process.")

    runner = _runner(settings)
    if runner is not None and settings.recon_catalog:
        from rca_engine.analyze import analyze

        scoped = analyze(runner, recon_id, settings.recon_catalog, settings.recon_schema,
                         dialect=settings.dialect, drilldown=True, only_table=only_table,
                         mapping=_mapping(settings), use_lineage=settings.use_lineage,
                         max_lineage_hops=settings.max_lineage_hops)
        _maybe_llm_fallback(settings, scoped, runner)
        _merge_into_bundle(settings, recon_id, scoped)
        return scoped

    # Demo replay: slice the bundled result down to the requested table.
    full = load_result(settings, recon_id)
    if full is None:
        raise RuntimeError(f"No warehouse configured and no bundle for '{recon_id}'.")
    return _slice_result(full, only_table)


def _slice_result(result: RcaResult, only_table: str) -> RcaResult:
    t = only_table.lower()
    findings = [f for f in result.findings if _short(f.target_table).lower() == t]
    summaries = [s for s in result.table_summaries if _short(s.target_table).lower() == t]
    return RcaResult(recon_id=result.recon_id, dialect=result.dialect,
                     findings=findings, table_summaries=summaries)


def _merge_into_bundle(settings: Settings, recon_id: str, scoped: RcaResult) -> None:
    """Fold a freshly-analyzed table into the recon's on-disk bundle (idempotent per table)."""
    from rca_engine.report import write_rca_bundle

    if not settings.bundles_dir:
        return
    existing = load_result(settings, recon_id)
    scoped_names = {_short(s.target_table).lower() for s in scoped.table_summaries}
    findings = list(scoped.findings)
    summaries = list(scoped.table_summaries)
    if existing is not None:
        findings += [f for f in existing.findings if _short(f.target_table).lower() not in scoped_names]
        summaries += [s for s in existing.table_summaries
                      if _short(s.target_table).lower() not in scoped_names]
    merged = RcaResult(recon_id=recon_id, dialect=scoped.dialect,
                       findings=findings, table_summaries=summaries)
    try:
        write_rca_bundle(merged, settings.bundles_dir, recon_id, combined=False)
    except Exception as exc:  # persistence is best-effort; the view is still returned
        print(f"[rca] could not persist bundle for {recon_id}: {exc}")


def build_table_view(result: RcaResult, table: str) -> dict[str, Any]:
    """Structured single-table result for the on-demand UI."""
    t = table.lower()
    findings = sorted((f for f in result.findings if _short(f.target_table).lower() == t),
                      key=severity_score, reverse=True)
    summary = next((s for s in result.table_summaries if _short(s.target_table).lower() == t), None)
    verdicts: dict[str, int] = {}
    for f in findings:
        if f.top_hypothesis:
            v = f.top_hypothesis.verdict.value
            verdicts[v] = verdicts.get(v, 0) + 1
    return {
        "recon_id": result.recon_id,
        "table": table,
        "verdict_meta": _VERDICT_META,
        "verdict_counts": verdicts,
        "summary": None if summary is None else {
            "source_table": summary.source_table,
            "target_table": summary.target_table,
            "source_count": summary.source_count,
            "target_count": summary.target_count,
            "missing_in_target": summary.missing_in_target,
            "missing_in_source": summary.missing_in_source,
            "absolute_mismatch": summary.absolute_mismatch,
            "row_match_pct": summary.row_match_pct,
            "schema_ok": summary.schema_ok,
        },
        "clean": len(findings) == 0,
        "findings": [_finding_view(f) for f in findings],
    }


# --------------------------------------------------------------------------- #
# Full-run analysis + notebook publishing (background job)
# --------------------------------------------------------------------------- #
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def workspace_host() -> str:
    return get_workspace_host()


def _ensure_folder(w, folder: str) -> None:
    """mkdirs, self-healing the deterministic ``rca_<id>`` path if a stale
    non-directory object (e.g. a notebook from an older publish) squats on it."""
    try:
        w.workspace.mkdirs(folder)
        return
    except Exception:
        pass
    from databricks.sdk.service.workspace import ObjectType
    try:
        obj = w.workspace.get_status(folder)
        if obj and obj.object_type == ObjectType.DIRECTORY:
            return  # already a folder; mkdirs quirk, fine
        w.workspace.delete(folder, recursive=False)  # stale notebook/file at our path
    except Exception:
        pass
    w.workspace.mkdirs(folder)


def _notebook_base(settings: Settings, w) -> str:
    """Workspace folder the notebooks are published under (configurable; defaults
    to the running identity's home)."""
    if settings.notebook_dir:
        return settings.notebook_dir.rstrip("/")
    try:
        user = w.current_user.me().user_name
    except Exception:
        user = "unknown"
    return f"/Workspace/Users/{user}/rca_notebooks"


def publish_notebooks(settings: Settings, recon_id: str, result: RcaResult,
                      notebook_dir: str | None = None) -> str:
    """Write the per-table RCA notebooks (+ index) into the workspace via the SDK
    so they open as real, runnable Databricks notebooks. Returns the folder path.
    ``notebook_dir`` overrides the configured/default base for this run."""
    from databricks.sdk.service.workspace import ImportFormat

    from rca_engine.report import (
        _subresult,
        _target_tables,
        build_index_notebook,
        build_notebook,
    )

    w = get_workspace_client()
    base = notebook_dir.strip().rstrip("/") if notebook_dir and notebook_dir.strip() else _notebook_base(settings, w)
    folder = f"{base}/rca_{recon_id}"
    _ensure_folder(w, folder)

    def _imp(name: str, nb: dict[str, Any]) -> None:
        content = base64.b64encode(json.dumps(nb).encode()).decode()
        w.workspace.import_(path=f"{folder}/{name}", format=ImportFormat.JUPYTER,
                            content=content, overwrite=True)

    tables = _target_tables(result)
    table_files: dict[str, str] = {}
    for tbl in tables:
        short = tbl.split(".")[-1].strip("`") or tbl
        name = re.sub(r"[^0-9A-Za-z_.-]", "_", short)
        if name in table_files.values():
            name = re.sub(r"[^0-9A-Za-z_.-]", "_", tbl)
        _imp(name, build_notebook(_subresult(result, tbl)))
        table_files[tbl] = name
    if len(tables) > 1:
        _imp("00_index", build_index_notebook(result, table_files))
    return folder


def publish_table_notebook(settings: Settings, recon_id: str, result: RcaResult,
                           notebook_dir: str | None = None) -> dict[str, Any]:
    """Publish the notebook for a single-table RCA result into the workspace (same
    ``rca_<recon_id>/`` folder the full run uses) and return the notebook path + URL."""
    from databricks.sdk.service.workspace import ImportFormat

    from rca_engine.report import _subresult, _target_tables, build_notebook

    tables = _target_tables(result)
    if not tables:
        return {"notebook_error": "No target table to publish."}
    tbl = tables[0]

    w = get_workspace_client()
    base = notebook_dir.strip().rstrip("/") if notebook_dir and notebook_dir.strip() else _notebook_base(settings, w)
    folder = f"{base}/rca_{recon_id}"
    _ensure_folder(w, folder)

    short = tbl.split(".")[-1].strip("`") or tbl
    name = re.sub(r"[^0-9A-Za-z_.-]", "_", short)
    path = f"{folder}/{name}"
    content = base64.b64encode(json.dumps(build_notebook(_subresult(result, tbl))).encode()).decode()
    w.workspace.import_(path=path, format=ImportFormat.JUPYTER, content=content, overwrite=True)

    host = get_workspace_host()
    return {
        "notebook_path": path,
        "notebook_url": f"{host}/#workspace{path}" if host else None,
        "notebook_folder": folder,
    }


def full_run_status(recon_id: str) -> dict[str, Any]:
    with _JOBS_LOCK:
        return dict(_JOBS.get(recon_id) or {"state": "idle"})


def start_full_run(settings: Settings, recon_id: str, drilldown: bool = True,
                   notebook_dir: str | None = None) -> dict[str, Any]:
    """Kick off (in a background thread) a full-run RCA: analyze every table, write
    the complete bundle so the dashboard is populated, and publish notebooks to the
    workspace. Returns immediately with the job status; poll ``full_run_status``.
    ``notebook_dir`` optionally overrides where the notebooks are published."""
    if not (settings.has_warehouse and settings.recon_catalog):
        return {"state": "error", "message": "No warehouse/catalog configured for live analysis."}
    with _JOBS_LOCK:
        cur = _JOBS.get(recon_id)
        if cur and cur.get("state") == "running":
            return dict(cur)
        _JOBS[recon_id] = {"state": "running", "message": "Analyzing all tables (ingest → classify → drill-down)…",
                           "started": time.time()}
    threading.Thread(target=_run_full, args=(settings, recon_id, drilldown, notebook_dir),
                     daemon=True).start()
    with _JOBS_LOCK:
        return dict(_JOBS[recon_id])


def _analyze_publish(settings: Settings, recon_id: str, drilldown: bool,
                     notebook_dir: str | None = None, *, run_id: str | None = None,
                     tool: str = "app", started: float | None = None,
                     source_schema: str | None = None, target_schema: str | None = None,
                     audit: bool = True) -> dict[str, Any]:
    """Analyze the whole run, persist the bundle (so the dashboard is populated), and
    publish notebooks. Returns a status dict (shared by the full-run and recon jobs).
    Appends an ``rca`` row to the audit trail (grouped by ``run_id``) unless disabled."""
    from rca_engine.analyze import analyze
    from rca_engine.report import write_rca_bundle

    started = started or time.time()

    # Preferred path: invoke the Genie Code skill as a Databricks Job so the skill's own
    # code does all actions (RCA + notebook publish + audit). The app just reads results.
    from .skill_job import run_skill_job, skill_job_ready

    if skill_job_ready(settings):
        status = run_skill_job(settings, mode="rca", recon_id=recon_id)
        if status.get("state") == "done":
            return status
        print(f"[rca] skill job failed ({status.get('message')}); falling back to in-process.")

    runner = _runner(settings)
    result = analyze(runner, recon_id, settings.recon_catalog,
                     settings.recon_schema, dialect=settings.dialect, drilldown=drilldown,
                     mapping=_mapping(settings), use_lineage=settings.use_lineage,
                     max_lineage_hops=settings.max_lineage_hops)
    _maybe_llm_fallback(settings, result, runner)
    try:
        write_rca_bundle(result, settings.bundles_dir, recon_id, combined=False)
    except Exception as exc:  # dashboard can still read live; log and continue
        print(f"[rca] local bundle write failed for {recon_id}: {exc}")
    notebook_path, publish_error = None, None
    try:
        notebook_path = publish_notebooks(settings, recon_id, result, notebook_dir=notebook_dir)
    except Exception as exc:
        publish_error = str(exc)
        print(f"[rca] notebook publish failed for {recon_id}: {exc}")
    message = ("Full RCA complete." if notebook_path
               else f"RCA complete; notebook publish failed: {publish_error}")
    if audit:
        log_audit(_runner(settings), settings.audit_table, operation="rca",
                  status="ok", tool=tool, run_id=run_id, run_by=_audit_user(),
                  catalog=settings.recon_catalog, source_schema=source_schema,
                  target_schema=target_schema, recon_id=recon_id,
                  table_pairs=len(result.table_summaries), tables_with_diffs=_diffs_count(result),
                  findings_total=len(result.findings), notebook_path=notebook_path,
                  message=message, started_ts=started)
    return {
        "state": "done",
        "message": message,
        "notebook_path": notebook_path,
        "notebook_url": (f"{get_workspace_host()}/#workspace{notebook_path}"
                         if notebook_path and get_workspace_host() else None),
        "tables": len(result.table_summaries),
        "findings": len(result.findings),
        "finished": time.time(),
    }


def _run_full(settings: Settings, recon_id: str, drilldown: bool,
              notebook_dir: str | None = None) -> None:
    started = time.time()
    try:
        status = _analyze_publish(settings, recon_id, drilldown, notebook_dir,
                                  tool="app", started=started)
    except Exception as exc:
        status = {"state": "error", "message": str(exc), "finished": time.time()}
        log_audit(_runner(settings), settings.audit_table, operation="rca", status="error",
                  tool="app", run_by=_audit_user(), catalog=settings.recon_catalog,
                  recon_id=recon_id, message=str(exc), started_ts=started)
    with _JOBS_LOCK:
        _JOBS[recon_id] = status


# --------------------------------------------------------------------------- #
# Trigger a reconcile from the app (auto-detect keys, auto-fix, then RCA)
# --------------------------------------------------------------------------- #
_RECON_JOBS: dict[str, dict[str, Any]] = {}
_RECON_LOCK = threading.Lock()


def recon_job_status(token: str) -> dict[str, Any]:
    with _RECON_LOCK:
        return dict(_RECON_JOBS.get(token) or {"state": "idle"})


def start_recon(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Kick off (background) an app-native reconcile of the requested table pairs,
    then optionally continue into the full RCA. Returns a ``token`` to poll via
    ``recon_job_status``."""
    if not (settings.has_warehouse and settings.recon_catalog):
        return {"state": "error", "message": "No warehouse/catalog configured to run a reconcile."}
    tables = payload.get("tables") or []
    if not tables:
        return {"state": "error", "message": "No tables provided."}
    token = uuid.uuid4().hex
    with _RECON_LOCK:
        _RECON_JOBS[token] = {"state": "running", "phase": "reconciling", "token": token,
                              "message": "Starting reconcile…", "done": 0, "total": len(tables),
                              "pairs": [], "recon_id": None, "started": time.time()}
    threading.Thread(target=_run_recon, args=(settings, token, payload), daemon=True).start()
    return recon_job_status(token)


def _run_recon_via_skill(settings: Settings, token: str, payload: dict[str, Any],
                         src_schema: str, tgt_schema: str, _set) -> None:
    """Run the full reconcile + RCA through the Genie Code skill (as a serverless job).

    The skill's ``reconcile_and_run`` auto-detects join keys, reconciles every pair, runs
    the RCA, publishes notebooks, and audits — all inside the job. The app polls it and
    surfaces the recon_id + dashboard + notebook link when it finishes."""
    from .skill_job import run_skill_job

    started = _RECON_JOBS.get(token, {}).get("started") or time.time()
    tables = payload.get("tables", [])

    def _status(msg: str) -> None:
        _set(message=msg)

    status = run_skill_job(
        settings, mode="reconcile_and_run", source_schema=src_schema, target_schema=tgt_schema,
        tables=tables, on_status=_status,
    )
    if status.get("state") != "done":
        _set(state="error", phase="reconciling", message=status.get("message", "Skill job failed."),
             run_page_url=status.get("run_page_url"), finished=time.time())
        return
    rid = status.get("recon_id")
    dashboard = f"/runs/{rid}" if rid else None
    _set(state="done", phase="done", recon_id=rid, dashboard=dashboard,
         notebook_path=status.get("notebook_path"), notebook_url=status.get("notebook_url"),
         tables=status.get("tables"), findings=status.get("findings"),
         run_page_url=status.get("run_page_url"), finished=time.time(),
         message=f"Done via Genie Code skill — recon_id ready, RCA complete. "
                 f"{status.get('message', '')}")


def _run_recon(settings: Settings, token: str, payload: dict[str, Any]) -> None:
    from rca_engine.reconcile import TablePairSpec, run_reconcile

    def _set(**kw):
        with _RECON_LOCK:
            _RECON_JOBS[token] = {**_RECON_JOBS.get(token, {}), **kw}

    try:
        catalog = settings.recon_catalog
        src_schema = (payload.get("source_schema") or settings.source_schema or "").strip()
        tgt_schema = (payload.get("target_schema") or settings.target_schema or "").strip()
        if not src_schema or not tgt_schema:
            _set(state="error", message="source_schema and target_schema are required.",
                 finished=time.time())
            return

        # Preferred path: hand the whole reconcile + RCA to the Genie Code skill as a job.
        from .skill_job import run_skill_job, skill_job_ready

        if skill_job_ready(settings):
            _run_recon_via_skill(settings, token, payload, src_schema, tgt_schema, _set)
            return
        specs = [
            TablePairSpec(
                source_table=(t.get("source") or t.get("source_table") or "").strip(),
                target_table=(t.get("target") or t.get("target_table") or "").strip(),
                join_keys=[k for k in (t.get("join_keys") or []) if k],
                column_mapping={k: v for k, v in (t.get("column_mapping") or {}).items() if k and v},
            )
            for t in payload.get("tables", [])
            if (t.get("source") or t.get("source_table"))
        ]

        def _progress(done: int, total: int, pair) -> None:
            with _RECON_LOCK:
                job = _RECON_JOBS.get(token, {})
                pairs = job.get("pairs", []) + [pair.to_dict()]
                _RECON_JOBS[token] = {**job, "done": done, "total": total, "pairs": pairs,
                                      "message": f"Reconciled {done}/{total}: {pair.source_table} "
                                                 f"({pair.status})"}

        started = _RECON_JOBS.get(token, {}).get("started") or time.time()
        result = run_reconcile(
            _runner(settings), catalog, src_schema, tgt_schema, specs,
            recon_schema=settings.recon_schema,
            sample_limit=int(payload.get("sample_limit", 100)),
            max_key_tries=int(payload.get("max_key_tries", 8)),
            progress=_progress,
        )
        summary = result.to_dict()
        ok = summary["pairs_ok"]
        # Audit the reconcile step (grouped with the RCA step by run_id=token).
        log_audit(_runner(settings), settings.audit_table, operation="reconcile",
                  status="ok" if ok else "error", tool="app", run_id=token, run_by=_audit_user(),
                  catalog=catalog, source_schema=src_schema, target_schema=tgt_schema,
                  recon_id=result.recon_id, tables=summary["pairs"], table_pairs=len(specs),
                  pairs_ok=ok, pairs_error=summary["pairs_error"], started_ts=started,
                  message=f"Reconciled {ok}/{len(specs)} pair(s).")
        if ok == 0:
            _set(state="error", phase="reconciling", recon_id=None, pairs=summary["pairs"],
                 message="Reconcile produced no comparable pairs — see per-table errors.",
                 finished=time.time())
            return
        dashboard = f"/runs/{result.recon_id}"
        _set(phase="analyzing", recon_id=result.recon_id, pairs=summary["pairs"],
             dashboard=dashboard, message=f"Reconcile complete ({ok} pair(s)). Running RCA…")

        if payload.get("auto_analyze", True):
            try:
                status = _analyze_publish(settings, result.recon_id,
                                          drilldown=bool(payload.get("drilldown", True)),
                                          notebook_dir=payload.get("notebook_dir"),
                                          run_id=token, tool="app", started=started,
                                          source_schema=src_schema, target_schema=tgt_schema)
                _set(state="done", phase="done", recon_id=result.recon_id, dashboard=dashboard,
                     pairs=summary["pairs"], notebook_path=status.get("notebook_path"),
                     notebook_url=status.get("notebook_url"), tables=status.get("tables"),
                     findings=status.get("findings"), finished=time.time(),
                     message=f"Done — reconciled {ok} pair(s), RCA complete. {status.get('message', '')}")
            except Exception as exc:
                _set(state="done", phase="done", recon_id=result.recon_id, dashboard=dashboard,
                     pairs=summary["pairs"], finished=time.time(),
                     message=f"Reconcile complete ({ok} pair(s)); RCA failed: {exc}")
        else:
                _set(state="done", phase="done", recon_id=result.recon_id, dashboard=dashboard,
                     pairs=summary["pairs"], finished=time.time(),
                     message=f"Reconcile complete — {ok} pair(s). recon_id ready.")
    except Exception as exc:
        _set(state="error", message=str(exc), finished=time.time())
        log_audit(_runner(settings), settings.audit_table, operation="reconcile", status="error",
                  tool="app", run_id=token, run_by=_audit_user(), catalog=settings.recon_catalog,
                  message=str(exc))


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
