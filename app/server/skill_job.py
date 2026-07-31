"""Invoke the Genie Code skill as a Databricks Job (serverless) and read results back.

This is how the ReconResolve App makes the **skill itself do all actions**: instead of
calling ``rca_engine`` in-process, the app submits the skill's ``job_entry`` notebook as
a one-time Jobs run on **serverless compute**. That notebook imports the deployed skill
(``skill/rca-recon/scripts/run_rca.py``) and runs ``reconcile`` / ``run`` /
``reconcile_and_run`` — the exact code Genie Code runs interactively — writing the RCA
bundle (JSON + SUMMARY + per-table notebooks) into a workspace folder.

The app then:
  * polls the run to completion,
  * reads the small JSON summary the notebook returns via ``dbutils.notebook.exit``,
  * downloads the full ``rca_<id>.json`` (+ ``SUMMARY.md``) back into ``bundles_dir`` so
    the dashboard renders,
and returns a status dict shaped like the in-process path (drop-in).

Everything is best-effort and defensive: submit/permission/serverless failures surface
as ``state="error"`` with a message; the caller can fall back to the in-process path.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Optional

from .config import Settings, get_workspace_client, get_workspace_host

_TERMINAL = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}


def skill_job_ready(settings: Settings) -> bool:
    """True when the app is configured to drive the skill as a job."""
    return bool(settings.use_skill_job and settings.skill_notebook and settings.skill_dir)


def _fetch_bundle(w, settings: Settings, recon_id: str, folder: Optional[str],
                  fetch_dir: Optional[str] = None) -> Optional[str]:
    """Download the skill-written bundle (JSON + SUMMARY) from the workspace ``folder``
    into ``fetch_dir`` (default the app's ``bundles_dir``) so the existing loader/dashboard
    can read it. Returns the local folder path, or ``None`` if nothing could be fetched."""
    if not folder:
        return None
    base = fetch_dir or settings.bundles_dir
    local_dir = os.path.join(base, f"rca_{recon_id}")
    try:
        os.makedirs(local_dir, exist_ok=True)
    except Exception as exc:
        print(f"[skill_job] cannot create local bundle dir {local_dir}: {exc}")
        return None
    got = False
    for name in (f"rca_{recon_id}.json", "SUMMARY.md"):
        remote = f"{folder.rstrip('/')}/{name}"
        try:
            with w.workspace.download(remote) as resp:  # WSFS file → bytes
                data = resp.read()
            with open(os.path.join(local_dir, name), "wb") as fh:
                fh.write(data)
            got = True
        except Exception as exc:
            print(f"[skill_job] could not download {remote}: {exc}")
    return local_dir if got else None


def run_skill_job(
    settings: Settings,
    *,
    mode: str = "reconcile_and_run",
    recon_id: Optional[str] = None,
    source_schema: Optional[str] = None,
    target_schema: Optional[str] = None,
    tables: Optional[list] = None,
    only_table: Optional[str] = None,
    out_dir: Optional[str] = None,
    fetch_dir: Optional[str] = None,
    timeout_s: int = 3600,
    poll_s: int = 8,
    on_status: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Submit the skill's job_entry notebook as a serverless one-time run and wait.

    ``mode`` = ``reconcile_and_run`` (default full pipeline), ``rca`` (existing recon_id),
    or ``reconcile`` (reconcile only). Returns a status dict with ``state`` in
    {done, error}, plus ``recon_id``, ``notebook_path``/``notebook_url`` (the workspace
    bundle folder), ``findings``, ``tables``, and ``run_page_url``.
    """
    from databricks.sdk.service import jobs

    def _say(msg: str) -> None:
        if on_status:
            try:
                on_status(msg)
            except Exception:
                pass

    if not skill_job_ready(settings):
        return {"state": "error", "message": "Skill job not configured (RCA_USE_SKILL_JOB / "
                                             "RCA_SKILL_NOTEBOOK / RCA_SKILL_DIR)."}

    out_base = (out_dir or settings.skill_out_dir or settings.notebook_dir or "").strip()
    if not out_base:
        return {"state": "error", "message": "No skill output dir (RCA_SKILL_OUT_DIR/RCA_NOTEBOOK_DIR)."}

    # Overrides the skill overlays onto its config.yml (skill code stays authoritative).
    cfg_over = {
        "recon_catalog": settings.recon_catalog,
        "recon_schema": settings.recon_schema,
        "dialect": settings.dialect,
        "output_dir": out_base,
        "audit_table": settings.audit_table or "off",
    }
    params = {
        "skill_dir": settings.skill_dir,
        "mode": mode,
        "recon_id": recon_id or "",
        "source_schema": source_schema or "",
        "target_schema": target_schema or "",
        "tables_json": json.dumps(tables or []),
        "out_dir": out_base,
        "config_json": json.dumps(cfg_over),
        "only_table": only_table or "",
    }

    w = get_workspace_client()
    _say("Submitting skill job (serverless)…")
    try:
        # No cluster spec → serverless jobs compute (when enabled in the workspace).
        waiter = w.jobs.submit(
            run_name=f"reconresolve-skill-{mode}-{(recon_id or 'new')[:8]}",
            tasks=[
                jobs.SubmitTask(
                    task_key="rca_recon_skill",
                    notebook_task=jobs.NotebookTask(
                        notebook_path=settings.skill_notebook, base_parameters=params
                    ),
                )
            ],
        )
    except Exception as exc:
        return {"state": "error", "message": f"Skill job submit failed: {exc}"}

    run_id = waiter.run_id
    host = get_workspace_host()
    run_page = f"{host}/#job/run/{run_id}" if host else None
    deadline = time.time() + timeout_s
    run = None
    while time.time() < deadline:
        try:
            run = w.jobs.get_run(run_id)
        except Exception as exc:
            print(f"[skill_job] get_run failed: {exc}")
            time.sleep(poll_s)
            continue
        state = run.state.life_cycle_state.value if run.state and run.state.life_cycle_state else ""
        if state in _TERMINAL:
            break
        _say(f"Skill job {state.lower() or 'running'}…")
        time.sleep(poll_s)

    if run is None:
        return {"state": "error", "message": "Skill job did not start.", "run_page_url": run_page}

    result_state = (run.state.result_state.value if run.state and run.state.result_state else "")
    if result_state != "SUCCESS":
        msg = (run.state.state_message if run.state else "") or result_state or "unknown"
        return {"state": "error", "message": f"Skill job failed: {msg}", "run_page_url": run_page}

    # Read the small JSON the notebook returned via dbutils.notebook.exit.
    exit_out: dict[str, Any] = {}
    try:
        task_run_id = run.tasks[0].run_id if run.tasks else run_id
        out = w.jobs.get_run_output(task_run_id)
        raw = out.notebook_output.result if out.notebook_output else None
        if raw:
            exit_out = json.loads(raw)
    except Exception as exc:
        print(f"[skill_job] get_run_output failed: {exc}")

    rid = exit_out.get("recon_id") or recon_id
    folder = exit_out.get("folder")
    local = _fetch_bundle(w, settings, rid, folder, fetch_dir=fetch_dir) if rid else None

    notebook_url = f"{host}/#workspace{folder}" if (host and folder) else None
    return {
        "state": "done",
        "message": "Skill job complete (Genie Code skill executed all actions).",
        "recon_id": rid,
        "notebook_path": folder,
        "notebook_url": notebook_url,
        "bundle_local": local,
        "findings": exit_out.get("findings"),
        "tables": exit_out.get("tables"),
        "run_page_url": run_page,
        "finished": time.time(),
    }
