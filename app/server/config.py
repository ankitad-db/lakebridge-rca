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
    notebook_dir: str = ""         # workspace folder to publish generated RCA notebooks into
    source_schema: str = ""        # default source schema for the trigger-recon form
    target_schema: str = ""        # default target schema for the trigger-recon form
    audit_table: str = ""          # fully-qualified Delta table for the pipeline audit trail
    llm_fallback: bool = False     # Tier-2: resolve residual findings via the Foundation Model API
    llm_endpoint: str = ""         # FM serving endpoint used for the Tier-2 fallback
    # Code-aware RCA: folder/file of migrated (transpiled) Databricks SQL. When set, the App
    # builds the per-column mapping so findings carry the 🔧 Transformation logic + culprit.
    transpiled_output_dir: str = ""
    recon_config_path: str = ""    # optional Lakebridge reconcile-config JSON (keys/mapping)
    source_scripts_dir: str = ""   # optional source-dialect DDL (declared source types)
    # UC lineage: depth-agnostic upstream trace-back + downstream blast radius (system.access.*).
    use_lineage: bool = True
    max_lineage_hops: int = 10
    use_skill_job: bool = False    # invoke the Genie Code skill as a Databricks Job (vs in-process)
    skill_notebook: str = ""       # workspace path of the deployed skill's job_entry notebook
    skill_dir: str = ""            # workspace folder of the deployed skill (contains scripts/, config.yml)
    skill_out_dir: str = ""        # workspace base the skill job writes rca_<id>/ bundles into
    profile: str = ""              # local CLI profile (ignored in-app)
    allow_ondemand: bool = False   # allow the app to run analyze() live (P2); off by default

    @property
    def has_warehouse(self) -> bool:
        return bool(self.warehouse_id)

    def with_catalog(self, catalog: str) -> "Settings":
        """A copy scoped to a different recon catalog (chosen in the UI). The audit
        table follows the catalog unless ``RCA_AUDIT_TABLE`` pins an explicit location."""
        import dataclasses

        if not catalog or catalog == self.recon_catalog:
            return self
        new = dataclasses.replace(self, recon_catalog=catalog)
        new.audit_table = _resolve_audit_table(catalog, self.recon_schema)
        return new

    def with_dialect(self, dialect: str) -> "Settings":
        """A copy scoped to a different source dialect (chosen in the UI). The dialect
        picks the knowledge base used for RCA classification + remediation."""
        import dataclasses

        if not dialect or dialect == self.dialect:
            return self
        return dataclasses.replace(self, dialect=dialect)

    def with_agentic(self, agentic: bool | None) -> "Settings":
        """A copy with the Tier-2 agentic layer forced on/off for one run (the UI's
        Deterministic ↔ Agentic choice). ``None`` keeps the deployment default. Agentic
        needs an endpoint configured; deterministic never calls the LLM."""
        import dataclasses

        if agentic is None or agentic == self.llm_fallback:
            return self
        return dataclasses.replace(self, llm_fallback=bool(agentic))


def load_settings() -> Settings:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    recon_catalog = os.environ.get("RCA_RECON_CATALOG", "")
    recon_schema = os.environ.get("RCA_RECON_SCHEMA", "reconcile")
    return Settings(
        warehouse_id=os.environ.get("RCA_WAREHOUSE_ID", os.environ.get("DATABRICKS_WAREHOUSE_ID", "")),
        recon_catalog=recon_catalog,
        recon_schema=recon_schema,
        dialect=os.environ.get("RCA_DIALECT", "snowflake"),
        bundles_dir=os.environ.get("RCA_BUNDLES_DIR", os.path.join(here, "bundles")),
        notebook_dir=os.environ.get("RCA_NOTEBOOK_DIR", ""),
        source_schema=os.environ.get("RCA_SOURCE_SCHEMA", ""),
        target_schema=os.environ.get("RCA_TARGET_SCHEMA", ""),
        audit_table=_resolve_audit_table(recon_catalog, recon_schema),
        llm_fallback=os.environ.get("RCA_LLM_FALLBACK", "").lower() in ("1", "true", "yes"),
        llm_endpoint=os.environ.get("RCA_LLM_ENDPOINT", "databricks-claude-opus-5"),
        transpiled_output_dir=os.environ.get("RCA_TRANSPILED_OUTPUT_DIR", ""),
        recon_config_path=os.environ.get("RCA_RECON_CONFIG_PATH", ""),
        source_scripts_dir=os.environ.get("RCA_SOURCE_SCRIPTS_DIR", ""),
        use_lineage=os.environ.get("RCA_USE_LINEAGE", "true").lower() in ("1", "true", "yes"),
        max_lineage_hops=int(os.environ.get("RCA_MAX_LINEAGE_HOPS", "10") or 10),
        use_skill_job=os.environ.get("RCA_USE_SKILL_JOB", "").lower() in ("1", "true", "yes"),
        skill_notebook=os.environ.get("RCA_SKILL_NOTEBOOK", ""),
        skill_dir=os.environ.get("RCA_SKILL_DIR", ""),
        skill_out_dir=os.environ.get("RCA_SKILL_OUT_DIR", ""),
        profile=os.environ.get("DATABRICKS_PROFILE", ""),
        allow_ondemand=os.environ.get("RCA_ALLOW_ONDEMAND", "").lower() in ("1", "true", "yes"),
    )


def _resolve_audit_table(recon_catalog: str, recon_schema: str) -> str:
    """Fully-qualified audit table. ``RCA_AUDIT_TABLE`` overrides; ``off``/``none``
    disables auditing; otherwise defaults to ``<catalog>.<recon_schema>.rca_genie_audit``
    when a catalog is configured."""
    override = os.environ.get("RCA_AUDIT_TABLE", "").strip()
    if override.lower() in ("off", "none", "false", "disabled"):
        return ""
    if override:
        return override
    return f"{recon_catalog}.{recon_schema}.rca_genie_audit" if recon_catalog else ""


def get_workspace_host() -> str:
    """Workspace URL with scheme (for building deep links to published notebooks)."""
    if IS_DATABRICKS_APP:
        host = os.environ.get("DATABRICKS_HOST", "")
        if host and not host.startswith("http"):
            host = f"https://{host}"
        return host
    try:
        return get_workspace_client().config.host or ""
    except Exception:
        return ""


def get_workspace_client():
    """Authenticated WorkspaceClient (service principal in-app, CLI profile locally)."""
    from databricks.sdk import WorkspaceClient

    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_PROFILE")
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()
