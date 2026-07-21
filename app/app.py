"""RCA Genie App — FastAPI entry point.

Serves a JSON API over the RCA engine and the built React frontend. The engine is
vendored under ``app/rca_engine`` (kept in sync with the repo root via ``make sync``)
so the app is self-contained for deployment.
"""

from __future__ import annotations

import os
import sys

# Make the vendored engine importable when running from the app folder.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from server.routes.api import router as api_router  # noqa: E402

app = FastAPI(title="RCA Genie — Post-Lakebridge Reconciliation RCA")
app.include_router(api_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


_FRONTEND = os.path.join(_HERE, "frontend", "dist")
if os.path.isdir(_FRONTEND):
    _assets = os.path.join(_FRONTEND, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Static file if it exists, else the SPA index (client-side routing).
        candidate = os.path.join(_FRONTEND, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_FRONTEND, "index.html"))
else:
    @app.get("/")
    def _no_frontend():
        return JSONResponse(
            {"message": "Frontend not built. Run `cd app/frontend && npm install && npm run build`.",
             "api": ["/api/health", "/api/config", "/api/runs", "/api/runs/{recon_id}"]}
        )
