# RCA Genie — Databricks App

A self-serve, Databricks-themed UI on top of the RCA engine. It turns a Lakebridge
reconcile run into a click-through experience: **pick a `recon_id` → dashboard →
drill into a table → export**. It complements the Genie Code skill (the agentic path);
the App is the at-a-glance / non-notebook path.

The App is a **reader/orchestrator**: it renders pre-computed RCA bundles
(`rca_<id>.json` + `SUMMARY.md`, produced by the skill/CLI or a scheduled job) and can
optionally run a live analysis. It never re-implements engine logic.

## Pages
- **Recon runs** — recent reconcile runs (via `list_recon_runs`); pick one.
- **Run dashboard** — KPI tiles (overall row match %, verdict counts), verdict-distribution
  donut, **🔺 Top priorities** (severity-ranked), and a per-table scorecard (worst first).
- **Table drill-down** — every finding for a table: severity, verdict, root cause, remediation,
  owner, the 5-source evidence + confirming query, and sample diffs.

## Architecture
```
app/
  app.py                # FastAPI: JSON API + serves the built React SPA
  app.yaml              # Databricks App config (command + env)
  requirements.txt      # backend deps (PyPI only)
  rca_engine/           # vendored engine (kept in sync via `make sync`)
  server/
    config.py           # dual-mode auth + settings (env-driven)
    rca_service.py      # discovery, bundle load, SDK statement runner, UI view builder
    routes/api.py       # /api/config, /api/runs, /api/runs/{id}, /api/runs/{id}/summary
  frontend/             # React + Vite + TS (Databricks dark theme)
  bundles/rca_<uuid>/   # committed demo bundles (3 runs) → the app renders with zero setup
  scripts/make_sample_bundle.py
```

## Run locally
```bash
# 1) Build the frontend (outputs app/frontend/dist)
cd app/frontend && npm install && npm run build && cd ..

# 2) Start the backend (serves API + SPA on :8000). Demo mode needs no workspace.
pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
# open http://localhost:8000
```

Frontend dev with hot reload (proxies /api → :8000):
```bash
cd app/frontend && npm run dev    # http://localhost:5173
```

Regenerate the demo bundles: `python scripts/make_sample_bundle.py`. This writes three
recon runs (realistic UUID `recon_id`s) driven by `migration/scenarios.yaml` — a retail
pilot cutover, an edge-case hardening run, and a clean post-fix re-run — so you can exercise
every scenario and the ✅ clean path.

## Configuration (env / `app.yaml`)
| Var | Purpose |
|---|---|
| `RCA_RECON_CATALOG` / `RCA_RECON_SCHEMA` | Where Lakebridge wrote `main`/`metrics`/`details` |
| `RCA_WAREHOUSE_ID` | SQL warehouse for live discovery/reads (bind a warehouse resource) |
| `RCA_BUNDLES_DIR` | Folder of pre-computed bundles (a UC Volume in-workspace) |
| `RCA_DIALECT` | Source dialect (default `snowflake`) |
| `RCA_ALLOW_ONDEMAND` | `true` to let the app run `analyze()` for a recon_id without a bundle |

With no `RCA_WAREHOUSE_ID`, the App runs in **demo mode** off the bundled sample.

## Deploy (outline)
```bash
databricks apps create rca-genie -p <profile>
databricks sync . /Workspace/Users/<you>/rca-genie \
  --exclude frontend/node_modules --exclude .venv --exclude __pycache__ -p <profile>
databricks apps deploy rca-genie \
  --source-code-path /Workspace/Users/<you>/rca-genie -p <profile>
```
Then bind a **SQL warehouse** resource (and a **UC Volume** for bundles) in the App UI and
set the env vars above. See the repo `databricks-apps` skill for the full deploy/troubleshoot flow.
