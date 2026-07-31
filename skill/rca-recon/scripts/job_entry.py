# Databricks notebook source
# MAGIC %md
# MAGIC # rca-recon skill — headless job entry
# MAGIC
# MAGIC This notebook lets a headless caller (the ReconResolve **Databricks App**) invoke the
# MAGIC **Genie Code skill** as a Databricks Job so *all actions run through the skill's own
# MAGIC code* (`run_rca.py`) — reconcile, RCA, notebook publish, and audit — instead of the app
# MAGIC re-implementing them. It reads its inputs from job parameters (widgets), dispatches to
# MAGIC the skill, and returns a small JSON result via `dbutils.notebook.exit`.
# MAGIC
# MAGIC Parameters: `skill_dir`, `mode` (`reconcile_and_run` | `rca` | `reconcile`),
# MAGIC `recon_id`, `source_schema`, `target_schema`, `tables_json`, `out_dir`, `config_json`.

# COMMAND ----------

# Dependencies the skill/engine need that aren't in the serverless base env
# (PyYAML for the knowledge base + config.yml; sqlglot for optional code-aware RCA).
# Kept as the first cell so the notebook-scoped install happens before any state is set.
%pip install pyyaml sqlglot

# COMMAND ----------

import json
import os
import sys

dbutils.widgets.text("skill_dir", "")          # workspace folder of the deployed skill (contains scripts/, config.yml)
dbutils.widgets.text("mode", "reconcile_and_run")
dbutils.widgets.text("recon_id", "")
dbutils.widgets.text("source_schema", "")
dbutils.widgets.text("target_schema", "")
dbutils.widgets.text("tables_json", "[]")      # JSON list: ["t"] or [{"source","target","join_keys","column_mapping"}]
dbutils.widgets.text("out_dir", "")            # where the skill writes rca_<id>/ (JSON + notebooks)
dbutils.widgets.text("config_json", "{}")      # overrides merged into config.yml (recon_catalog, recon_schema, dialect, audit_table)
dbutils.widgets.text("only_table", "")         # optional: scope RCA to one target table

skill_dir = dbutils.widgets.get("skill_dir").strip()
mode = dbutils.widgets.get("mode").strip() or "reconcile_and_run"
recon_id = dbutils.widgets.get("recon_id").strip()
source_schema = dbutils.widgets.get("source_schema").strip()
target_schema = dbutils.widgets.get("target_schema").strip()
tables = json.loads(dbutils.widgets.get("tables_json") or "[]")
out_dir = dbutils.widgets.get("out_dir").strip() or None
config_json = dbutils.widgets.get("config_json") or "{}"
only_table = dbutils.widgets.get("only_table").strip() or None

# Overrides (catalog/schema/dialect/audit/output_dir) flow to the skill via this env var,
# which run_rca._load_config() overlays onto config.yml — skill code stays authoritative.
os.environ["RCA_CONFIG_JSON"] = config_json

# COMMAND ----------

# Import the skill exactly as Genie Code would (rca_engine is vendored inside it).
for p in (os.path.join(skill_dir, "scripts"), skill_dir):
    if p and p not in sys.path:
        sys.path.insert(0, p)

import run_rca  # noqa: E402  (from the deployed skill/scripts)

# COMMAND ----------

folder = None
result = None
if mode == "reconcile":
    recon = run_rca.reconcile(spark, source_schema, target_schema, tables)
    recon_id = recon.recon_id
elif mode == "rca":
    if not recon_id:
        raise ValueError("mode=rca requires recon_id")
    result = run_rca.run(recon_id, spark, out_dir, only_table=only_table)
else:  # reconcile_and_run (default): the full 'do all actions' pipeline
    recon_id, result = run_rca.reconcile_and_run(spark, source_schema, target_schema, tables,
                                                 out_dir=out_dir)

# Resolve the folder the skill wrote to (same rule run_rca uses), so the app can fetch it.
if result is not None:
    resolved = run_rca._resolve_out_dir(out_dir or run_rca._load_config().get("output_dir")
                                        or "rca_notebooks", spark)
    folder = os.path.join(resolved, f"rca_{recon_id}")

out = {
    "recon_id": recon_id,
    "folder": folder,
    "findings": (len(result.findings) if result is not None else 0),
    "tables": (len(result.table_summaries) if result is not None else 0),
    "mode": mode,
}
print("SKILL_RESULT=" + json.dumps(out))

# COMMAND ----------

dbutils.notebook.exit(json.dumps(out))
