"""JSON API for the RCA App frontend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from .. import rca_service as svc
from ..config import IS_DATABRICKS_APP, load_settings

router = APIRouter()


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


@router.get("/runs/{recon_id}/summary", response_class=PlainTextResponse)
def get_summary(recon_id: str):
    md = svc.summary_md(load_settings(), recon_id)
    if md is None:
        raise HTTPException(status_code=404, detail="No summary available.")
    return md
