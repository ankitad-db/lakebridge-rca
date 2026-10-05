"""Trigger the REAL Lakebridge reconcile from the app.

Lakebridge reconcile is not a REST API — `databricks labs lakebridge reconcile` launches a
deployed Databricks job (``LAKEBRIDGE_Reconciliation_Runner``: a python-wheel task running
``databricks_labs_lakebridge``'s ``reconcile`` entry point, params ``operation_name`` +
``install_folder``). This module triggers that SAME job via ``jobs.run_now``, so the app runs
authentic Lakebridge reconcile — reading the workspace ``.lakebridge/reconcile.yml`` +
``recon_config_*.json`` — then hands the resulting ``recon_id`` to RCA.

NOTE: the tables reconciled come from the ``.lakebridge`` recon config authored per
deployment, NOT the app's table picker. So the app triggers Lakebridge's configured
reconcile and then root-causes whatever ``recon_id`` it produces.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .config import Settings, get_workspace_client, get_workspace_host

_TERMINAL = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}


def lakebridge_recon_ready(settings: Settings) -> bool:
    """True when the app is configured to run reconcile via the real Lakebridge job."""
    return bool(settings.use_lakebridge_recon and settings.lakebridge_job_id)


def _latest_recon_id(settings: Settings, exclude: Optional[str] = None) -> Optional[str]:
    """Newest recon_id in <catalog>.<schema>.main (to pick up the run Lakebridge just wrote).
    Deferred imports avoid a circular dependency with rca_service."""
    try:
        from rca_engine.discovery import list_recon_runs

        from . import rca_service

        runner = rca_service._runner(settings)
        if runner is None:
            return None
        runs = list_recon_runs(runner, settings.recon_catalog, settings.recon_schema, limit=5)
        for r in runs:
            rid = r.get("recon_id")
            if rid and rid != exclude:
                return rid
        return runs[0].get("recon_id") if runs else None
    except Exception as exc:
        print(f"[lakebridge_job] latest recon_id lookup failed: {exc}")
        return None


def run_lakebridge_reconcile(
    settings: Settings,
    operation_name: str = "reconcile",
    say: Optional[Callable[[str], None]] = None,
    timeout_s: int = 3600,
    poll_s: int = 10,
) -> dict[str, Any]:
    """``run_now`` the deployed Lakebridge reconcile job, wait for it, and return the newest
    ``recon_id`` it produced. Best-effort — returns ``{state, recon_id?, run_page_url?, message}``.

    ``operation_name`` is ``reconcile`` or ``aggregates-reconcile`` (the job's own parameter).
    """
    def _say(m: str) -> None:
        if say:
            say(m)

    if not lakebridge_recon_ready(settings):
        return {"state": "error", "message": "Lakebridge reconcile is not configured."}

    w = get_workspace_client()
    host = get_workspace_host()
    before = _latest_recon_id(settings)  # so we can detect the NEW run afterwards

    _say("Submitting Lakebridge reconcile job…")
    try:
        run = w.jobs.run_now(
            job_id=int(settings.lakebridge_job_id),
            job_parameters={
                "operation_name": operation_name,
                "install_folder": settings.lakebridge_install_folder,
            },
        )
    except Exception as exc:
        return {"state": "error", "message": f"Lakebridge job run_now failed: {exc}"}

    run_id = run.run_id
    run_page = f"{host}/#job/run/{run_id}" if host else None
    deadline = time.time() + timeout_s
    r = None
    while time.time() < deadline:
        try:
            r = w.jobs.get_run(run_id)
        except Exception as exc:
            print(f"[lakebridge_job] get_run failed: {exc}")
            time.sleep(poll_s)
            continue
        state = r.state.life_cycle_state.value if r.state and r.state.life_cycle_state else ""
        if state in _TERMINAL:
            break
        _say(f"Lakebridge reconcile {state.lower() or 'running'}… (real Lakebridge job)")
        time.sleep(poll_s)

    if r is None:
        return {"state": "error", "message": "Lakebridge run did not start.", "run_page_url": run_page}

    result_state = r.state.result_state.value if r.state and r.state.result_state else ""
    if result_state != "SUCCESS":
        msg = (r.state.state_message if r.state else "") or result_state or "unknown"
        return {"state": "error", "message": f"Lakebridge reconcile failed: {msg}",
                "run_page_url": run_page}

    recon_id = _latest_recon_id(settings, exclude=before)
    return {
        "state": "ok",
        "recon_id": recon_id,
        "run_page_url": run_page,
        "message": ("Lakebridge reconcile complete." if recon_id
                    else "Lakebridge reconcile complete (recon_id not resolved from main)."),
    }
