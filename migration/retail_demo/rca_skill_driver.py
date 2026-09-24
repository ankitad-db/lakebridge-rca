# Databricks notebook source
# MAGIC %pip install sqlglot pyyaml

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
# Invoke the deployed rca-recon skill exactly as Genie Code would: import its runner and
# call run() with the workspace Spark session. Params: recon_id, endpoint (FM endpoint for
# the Tier-2 agentic fallback; blank = pure deterministic), transpiled_dir (migrated-SQL
# artifact folder for the code-aware transform highlight).
import sys

SKILL = "/Workspace/Users/ankita.darekar@databricks.com/.assistant/skills/rca-recon"
for _p in (SKILL, SKILL + "/scripts"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

dbutils.widgets.text("recon_id", "")
dbutils.widgets.text("endpoint", "")
dbutils.widgets.text("transpiled_dir", "")
rid = dbutils.widgets.get("recon_id").strip()
ep = dbutils.widgets.get("endpoint").strip() or None
tdir = dbutils.widgets.get("transpiled_dir").strip() or None

print(f"recon_id={rid}  endpoint={ep}  transpiled_dir={tdir}")

import run_rca

res = run_rca.run(rid, spark, llm_endpoint=ep, transpiled_output_dir=tdir)
print("FINDINGS_TOTAL:", len(res.findings))
