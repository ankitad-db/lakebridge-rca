"""App configuration + dual-mode auth (Databricks App vs local dev).

The engine is backend-agnostic (a ``QueryRunner`` protocol). In the App we back it
with the Databricks SDK's Statement Execution API using the app's own credentials
(service principal in the workspace, CLI profile locally), so reads respect Unity
Catalog permissions. No tokens are ever entered by the user.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Auto-set by the Databricks Apps runtime.
IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))


@dataclass
class Settings:
    warehouse_id: str = ""
    recon_catalog: str = ""
    recon_schema: str = "reconcile"
    dialect: str = "snowflake"
    bundles_dir: str = ""          # where pre-computed RCA bundles live (UC Volume or local)
    profile: str = ""              # local CLI profile (ignored in-app)
    allow_ondemand: bool = False   # allow the app to run analyze() live (P2); off by default

    @property
    def has_warehouse(self) -> bool:
        return bool(self.warehouse_id)


def load_settings() -> Settings:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return Settings(
        warehouse_id=os.environ.get("RCA_WAREHOUSE_ID", os.environ.get("DATABRICKS_WAREHOUSE_ID", "")),
        recon_catalog=os.environ.get("RCA_RECON_CATALOG", ""),
        recon_schema=os.environ.get("RCA_RECON_SCHEMA", "reconcile"),
        dialect=os.environ.get("RCA_DIALECT", "snowflake"),
        bundles_dir=os.environ.get("RCA_BUNDLES_DIR", os.path.join(here, "bundles")),
        profile=os.environ.get("DATABRICKS_PROFILE", ""),
        allow_ondemand=os.environ.get("RCA_ALLOW_ONDEMAND", "").lower() in ("1", "true", "yes"),
    )


def get_workspace_client():
    """Authenticated WorkspaceClient (service principal in-app, CLI profile locally)."""
    from databricks.sdk import WorkspaceClient

    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_PROFILE")
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()
