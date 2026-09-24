"""JSON API for the RCA App frontend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import rca_service as svc
from ..config import IS_DATABRICKS_APP, Settings, load_settings

router = APIRouter()


def _settings(catalog: str | None = None, dialect: str | None = None) -> Settings:
    """Settings for the request, optionally scoped to a UI-selected catalog + dialect."""
    s = load_settings()
    if catalog:
        s = s.with_catalog(catalog)
    if dialect:
        s = s.with_dialect(dialect)
    return s


class AnalyzeRequest(BaseModel):
    table: str
    notebook_dir: str | None = None
    publish: bool = True
    agentic: bool | None = None   # UI toggle: True=deterministic+agentic, False=deterministic-only, None=default


class FullRunRequest(BaseModel):
    drilldown: bool = True
    notebook_dir: str | None = None
    agentic: bool | None = None   # UI toggle (see AnalyzeRequest)


class ReconTablePair(BaseModel):
    source: str
    target: str | None = None
    join_keys: list[str] | None = None
    column_mapping: dict[str, str] | None = None


class ReconTriggerRequest(BaseModel):
    catalog: str | None = None
    dialect: str | None = None
    source_schema: str | None = None
    target_schema: str | None = None
    tables: list[ReconTablePair]
    auto_analyze: bool = True
    drilldown: bool = True
    notebook_dir: str | None = None
    sample_limit: int = 100
    max_key_tries: int = 8
    agentic: bool | None = None   # RCA mode for the auto-analyze step (deterministic vs agentic)


@router.get("/config")
def get_config():
    s = load_settings()
    return {
        "recon_catalog": s.recon_catalog,
        "recon_schema": s.recon_schema,
        "dialect": s.dialect,
        "has_warehouse": s.has_warehouse,
        "allow_ondemand": s.allow_ondemand,
        "in_app": IS_DATABRICKS_APP,
        "demo_mode": not s.has_warehouse,
        "workspace_host": svc.workspace_host(),
        "notebook_dir": s.notebook_dir,
        "source_schema": s.source_schema,
        "target_schema": s.target_schema,
        "audit_table": s.audit_table,
    }


@router.get("/catalogs")
def get_catalogs():
    """Catalogs the app can see (for the UI catalog picker)."""
    return {"catalogs": svc.list_catalogs(load_settings())}


@router.get("/dialects")
def get_dialects():
    """Source dialects with a curated knowledge base (for the UI dialect picker)."""
    return {"dialects": svc.list_dialects(load_settings())}


@router.get("/audit")
def get_audit(limit: int = 50, catalog: str | None = None):
    """Recent pipeline audit rows (reconcile + RCA history), newest first."""
    s = _settings(catalog)
    return {"audit_table": s.audit_table, "rows": svc.list_audit(s, limit=limit)}


@router.get("/schemas")
def get_schemas(catalog: str | None = None):
    """Schemas in the recon catalog (for the trigger-recon form)."""
    return {"schemas": svc.list_schemas(_settings(catalog))}


@router.get("/schemas/{schema}/tables")
def get_schema_tables(schema: str, catalog: str | None = None):
    """Tables in a schema of the recon catalog (for the trigger-recon form)."""
    return {"schema": schema, "tables": svc.list_schema_tables(_settings(catalog), schema)}


@router.post("/recon/trigger")
def trigger_recon(req: ReconTriggerRequest, catalog: str | None = None, dialect: str | None = None):
    """Trigger an app-native reconcile (auto-detect keys, auto-fix, then RCA).
    Returns a token immediately; poll GET /recon/job/{token}."""
    payload = req.model_dump()
    return svc.start_recon(_settings(req.catalog or catalog, req.dialect or dialect).with_agentic(req.agentic), payload)


@router.get("/recon/job/{token}")
def get_recon_job(token: str):
    """Status of a triggered reconcile job (phase, per-pair results, recon_id, link)."""
    return svc.recon_job_status(token)


@router.get("/runs")
def get_runs(catalog: str | None = None):
    return {"runs": svc.list_runs(_settings(catalog))}


@router.get("/runs/{recon_id}")
def get_run(recon_id: str, catalog: str | None = None, dialect: str | None = None):
    result = svc.load_result(_settings(catalog, dialect), recon_id)
    if result is None:
        raise HTTPException(status_code=404,
                            detail=f"No RCA bundle for '{recon_id}'. Generate one with the "
                                   f"skill/CLI, or enable on-demand analysis.")
    return svc.build_view(result)


@router.get("/runs/{recon_id}/tables")
def get_tables(recon_id: str, catalog: str | None = None):
    """Table pairs in a recon run, for the one-table-at-a-time analyze flow."""
    tables = svc.list_tables(_settings(catalog), recon_id)
    if not tables:
        raise HTTPException(status_code=404,
                            detail=f"No tables found for recon '{recon_id}'. Check the "
                                   f"recon_id, catalog/schema, or warehouse configuration.")
    return {"recon_id": recon_id, "tables": tables}


@router.post("/runs/{recon_id}/analyze")
def analyze_table(recon_id: str, req: AnalyzeRequest, catalog: str | None = None,
                  dialect: str | None = None):
    """Run the RCA for one table (calls the engine the Genie skill uses), publish its
    notebook to the workspace, and return the view + notebook link."""
    settings = _settings(catalog, dialect).with_agentic(req.agentic)
    try:
        result = svc.run_analysis(settings, recon_id, req.table)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc
    view = svc.build_table_view(result, req.table)
    # Publish a runnable notebook (folder rca_<recon_id>/) when running live.
    if req.publish and settings.has_warehouse:
        try:
            view["notebook"] = svc.publish_table_notebook(settings, recon_id, result,
                                                          notebook_dir=req.notebook_dir)
        except Exception as exc:  # analysis still succeeded; surface publish failure softly
            view["notebook"] = {"notebook_error": str(exc)}
    return view


@router.post("/runs/{recon_id}/analyze-all")
def analyze_all(recon_id: str, req: FullRunRequest | None = None, catalog: str | None = None,
                dialect: str | None = None):
    """Kick off a full-run RCA (all tables) + publish notebooks to the workspace.
    Returns immediately; poll GET /runs/{recon_id}/job for progress."""
    drilldown = req.drilldown if req else True
    notebook_dir = req.notebook_dir if req else None
    agentic = req.agentic if req else None
    return svc.start_full_run(_settings(catalog, dialect).with_agentic(agentic), recon_id,
                              drilldown=drilldown, notebook_dir=notebook_dir)


@router.get("/runs/{recon_id}/job")
def get_job(recon_id: str):
    """Status of the background full-run job for this recon (state/notebook link)."""
    return svc.full_run_status(recon_id)


@router.get("/runs/{recon_id}/summary", response_class=PlainTextResponse)
def get_summary(recon_id: str, catalog: str | None = None):
    md = svc.summary_md(_settings(catalog), recon_id)
    if md is None:
        raise HTTPException(status_code=404, detail="No summary available.")
    return md
