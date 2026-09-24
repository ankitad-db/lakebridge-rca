"""Run genuine Lakebridge reconcile on the two retail beds and print the recon_ids.

  HYBRID:        mig_hyb_src vs mig_hyb_tgt   (report_type=all)
  DETERMINISTIC: mig_det_src vs mig_det_tgt   (report_type=all) + aggregates-reconcile

Emits RECON_IDS={...} so downstream steps can pick them up. Run after build_retail_beds.py.
"""
import json
import os
import subprocess
import time

CAT = "fevm_ps_dr_us_east_2_catalog"
WH = "3220376d4497e2d7"
PROFILE = "ps-dr-east"
LB = "/Users/ankita.darekar@databricks.com/.lakebridge"
ENV = {**os.environ, "DATABRICKS_CONFIG_PROFILE": PROFILE}

TABLES = [
    {"source_name": "fact_sales", "target_name": "fact_sales", "join_columns": ["order_id"]},
    {"source_name": "dim_customer", "target_name": "dim_customer", "join_columns": ["customer_id"]},
    {"source_name": "dim_product", "target_name": "dim_product", "join_columns": ["product_id"]},
]
# deterministic bed: tax within-tolerance threshold + aggregate rules
DET_TABLES = json.loads(json.dumps(TABLES))
DET_TABLES[0]["column_thresholds"] = [
    {"column_name": "tax_rate", "lower_bound": "-0.01", "upper_bound": "0.01", "type": "decimal"}]
DET_TABLES[0]["aggregates"] = [
    {"type": "sum", "agg_columns": ["net_revenue"], "group_by_columns": ["is_active"]},
    {"type": "avg", "agg_columns": ["net_revenue"], "group_by_columns": ["is_active"]}]


def ycfg(src, tgt):
    return f"""metadata_config:
  catalog: {CAT}
  schema: reconcile
  volume: reconcile_volume
report_type: all
source:
  dialect: databricks
  catalog: {CAT}
  schema: {src}
target:
  catalog: {CAT}
  schema: {tgt}
version: 2
"""


def put(name, body):
    p = f"/tmp/{name}"
    open(p, "w").write(body)
    subprocess.run(["databricks", "workspace", "import", f"{LB}/{name}", "--file", p,
                    "--format", "AUTO", "--overwrite", "-p", PROFILE], capture_output=True)


def run_op(op):
    t0 = time.time()
    out = subprocess.run(["databricks", "labs", "lakebridge", op], input="\n",
                         capture_output=True, text=True, env=ENV).stderr
    rid = next((l.split("runs/")[1].split("`")[0].split()[0].strip() for l in out.splitlines() if "runs/" in l), None)
    print(f"  {op} job run: {rid}", flush=True)
    while rid:
        r = subprocess.run(["databricks", "jobs", "get-run", rid, "-p", PROFILE, "-o", "json"],
                           capture_output=True, text=True)
        try:
            st = (json.loads(r.stdout).get("status") or {}).get("state", "")
        except Exception:
            st = ""
        if st in ("TERMINATED", "INTERNAL_ERROR"):
            code = (json.loads(r.stdout).get("status", {}).get("termination_details") or {}).get("code", "")
            print(f"  {op}: {code} in {round(time.time()-t0)}s", flush=True)
            break
        time.sleep(12)


def latest_recon_ids(tgt_schema):
    q = (f"SELECT operation_name, recon_id FROM {CAT}.reconcile.main "
         f"WHERE target_table.schema='{tgt_schema}' "
         f"QUALIFY row_number() OVER (PARTITION BY operation_name ORDER BY recon_table_id DESC)=1")
    r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
                        json.dumps({"warehouse_id": WH, "statement": q, "wait_timeout": "40s"})],
                       capture_output=True, text=True)
    try:
        rows = json.loads(r.stdout).get("result", {}).get("data_array") or []
        return {op: rid for op, rid in rows}
    except Exception:
        return {}


def bed(name, src, tgt, tables, aggregates=False):
    print(f"[{name}] reconcile {src} -> {tgt}", flush=True)
    put("reconcile.yml", ycfg(src, tgt))
    put(f"recon_config_databricks_{CAT}_all.json", json.dumps({"tables": tables}, indent=2))
    run_op("reconcile")
    if aggregates:
        run_op("aggregates-reconcile")
    ids = latest_recon_ids(tgt)
    print(f"[{name}] RECON_IDS={json.dumps(ids)}", flush=True)
    return ids


if __name__ == "__main__":
    hyb = bed("HYBRID", "mig_hyb_src", "mig_hyb_tgt", TABLES, aggregates=False)
    det = bed("DETERMINISTIC", "mig_det_src", "mig_det_tgt", DET_TABLES, aggregates=True)
    print("ALL_RECON_IDS=" + json.dumps({"hybrid": hyb, "deterministic": det}))
