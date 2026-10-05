"""Build the HYBRID demo target (mig_rev_hyb_tgt) from the existing mig_rev_src source and
run a real Lakebridge reconcile. Reuses build_revenue_demo's helpers; only the target schema
and target SQL differ. Emits RECON_IDS at the end.

  python migration/retail_demo/build_hybrid_demo.py
"""
import json
import os
import subprocess
import time

import build_revenue_demo as B  # sql(), put(), CAT, WH, PROFILE, LB, ENV

TGT = "mig_rev_hyb_tgt"
SRC = "mig_rev_src"
HERE = os.path.dirname(os.path.abspath(__file__))
TABLES = [
    {"source_name": "fact_sales", "target_name": "fact_sales", "join_columns": ["order_id"]},
]


def ycfg():
    return f"""metadata_config:
  catalog: {B.CAT}
  schema: reconcile
  volume: reconcile_volume
report_type: all
source:
  dialect: databricks
  catalog: {B.CAT}
  schema: {SRC}
target:
  catalog: {B.CAT}
  schema: {TGT}
version: 2
"""


def run_reconcile():
    B.put("reconcile.yml", ycfg())
    B.put(f"recon_config_databricks_{B.CAT}_all.json", json.dumps({"tables": TABLES}, indent=2))
    t0 = time.time()
    out = subprocess.run(["databricks", "labs", "lakebridge", "reconcile"], input="\n",
                         capture_output=True, text=True, env=B.ENV).stderr
    rid = next((l.split("runs/")[1].split("`")[0].split()[0].strip()
                for l in out.splitlines() if "runs/" in l), None)
    print(f"  reconcile job run: {rid}", flush=True)
    while rid:
        r = subprocess.run(["databricks", "jobs", "get-run", rid, "-p", B.PROFILE, "-o", "json"],
                           capture_output=True, text=True)
        try:
            st = (json.loads(r.stdout).get("status") or {}).get("state", "")
        except Exception:
            st = ""
        if st in ("TERMINATED", "INTERNAL_ERROR"):
            code = (json.loads(r.stdout).get("status", {}).get("termination_details") or {}).get("code", "")
            print(f"  reconcile: {code} in {round(time.time()-t0)}s", flush=True)
            break
        time.sleep(12)


def latest():
    q = (f"SELECT recon_id, min(main.start_ts) AS ts FROM {B.CAT}.reconcile.main "
         f"WHERE target_table.schema='{TGT}' GROUP BY recon_id ORDER BY ts DESC LIMIT 1")
    r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", B.PROFILE, "--json",
                        json.dumps({"warehouse_id": B.WH, "statement": q, "wait_timeout": "40s"})],
                       capture_output=True, text=True)
    try:
        return (json.loads(r.stdout).get("result", {}).get("data_array") or [["?"]])[0][0]
    except Exception:
        return "?"


if __name__ == "__main__":
    print(f"[HYBRID] building target {TGT} (revenue_hybrid_target.sql) ...", flush=True)
    B.sql(f"CREATE SCHEMA IF NOT EXISTS {B.CAT}.{TGT}", f"schema {TGT}")
    B.run_target_file(os.path.join(HERE, "revenue_hybrid_target.sql"))
    print("[HYBRID] reconcile mig_rev_src -> mig_rev_hyb_tgt ...", flush=True)
    run_reconcile()
    print(f"[HYBRID] RECON_ID={latest()}", flush=True)
