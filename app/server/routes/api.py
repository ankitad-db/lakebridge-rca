"""JSON API for the RCA App frontend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import rca_service as svc
from ..config import IS_DATABRICKS_APP, load_settings

router = APIRouter()


class AnalyzeRequest(BaseModel):
    table: str
    notebook_dir: str | None = None
    publish: bool = True


class FullRunRequest(BaseModel):
    drilldown: bool = True
    notebook_dir: str | None = None


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
    }


@router.get("/runs")
def get_runs():
    return {"runs": svc.list_runs(load_settings())}


@router.get("/runs/{recon_id}")
def get_run(recon_id: str):
    result = svc.load_result(load_settings(), recon_id)
    if result is None:
        raise HTTPException(status_code=404,
                            detail=f"No RCA bundle for '{recon_id}'. Generate one with the "
                                   f"skill/CLI, or enable on-demand analysis.")
    return svc.build_view(result)


@router.get("/runs/{recon_id}/tables")
def get_tables(recon_id: str):
    """Table pairs in a recon run, for the one-table-at-a-time analyze flow."""
    tables = svc.list_tables(load_settings(), recon_id)
    if not tables:
        raise HTTPException(status_code=404,
                            detail=f"No tables found for recon '{recon_id}'. Check the "
                                   f"recon_id, catalog/schema, or warehouse configuration.")
    return {"recon_id": recon_id, "tables": tables}


@router.post("/runs/{recon_id}/analyze")
def analyze_table(recon_id: str, req: AnalyzeRequest):
    """Run the RCA for one table (calls the engine the Genie skill uses), publish its
    notebook to the workspace, and return the view + notebook link."""
    settings = load_settings()
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
def analyze_all(recon_id: str, req: FullRunRequest | None = None):
    """Kick off a full-run RCA (all tables) + publish notebooks to the workspace.
    Returns immediately; poll GET /runs/{recon_id}/job for progress."""
    drilldown = req.drilldown if req else True
    notebook_dir = req.notebook_dir if req else None
    return svc.start_full_run(load_settings(), recon_id, drilldown=drilldown, notebook_dir=notebook_dir)


@router.get("/runs/{recon_id}/job")
def get_job(recon_id: str):
    """Status of the background full-run job for this recon (state/notebook link)."""
    return svc.full_run_status(recon_id)


@router.get("/runs/{recon_id}/summary", response_class=PlainTextResponse)
def get_summary(recon_id: str):
    md = svc.summary_md(load_settings(), recon_id)
    if md is None:
        raise HTTPException(status_code=404, detail="No summary available.")
    return md
