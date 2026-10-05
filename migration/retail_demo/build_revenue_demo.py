"""Build the focused REVENUE demo bed (mig_rev_src/tgt) on ps-dr-east and run a real
Lakebridge reconcile — a single, clean recon whose HERO is the stale-monthly-FX defect.

  source  mig_rev_src.*   = correct EDW gold (ground truth)
  target  mig_rev_tgt.*   = migrated gold (built by revenue_target.sql, defect-carrying)

Seeded defects (and nothing else differs):
  * amount_usd   FX joined at MONTH-START instead of daily rate   -> HERO (migration-induced)
  * unit_price   ROUND(...,2)/DECIMAL(18,2)                        -> precision (deterministic)
  * tax_rate     +0.0005, declared +/-0.01 threshold              -> benign (within tolerance)
  * customer_name UPPER(TRIM(...))                                 -> string-format (deterministic)
  * dim_customer.segment  source-side reclassification            -> genuine upstream data

Run:  python migration/retail_demo/build_revenue_demo.py
Emits RECON_IDS={...} at the end.
"""
import json
import os
import subprocess
import sys
import time

CAT = "fevm_ps_dr_us_east_2_catalog"
WH = "4c79c6902dd2bbc2"
PROFILE = "ps-dr-east"
LB = "/Users/ankita.darekar@databricks.com/.lakebridge"
ENV = {**os.environ, "DATABRICKS_CONFIG_PROFILE": PROFILE}
N = 500_000
SRC = "mig_rev_src"
TGT = "mig_rev_tgt"
HERE = os.path.dirname(os.path.abspath(__file__))

ARR_CUR = "array('USD','EUR','GBP','JPY','INR')"
ARR_STATUS = "array('A','C','P','R')"
ARR_ORG = "array('Acme','Globex','Initech','Umbrella','Soylent')"
ARR_PERSON = "array('John Smith','Mary Jones','Wei Chen','Ana Silva','Omar Farah')"


def sql(stmt: str, label: str = "") -> None:
    t0 = time.time()
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
         json.dumps({"warehouse_id": WH, "statement": stmt, "wait_timeout": "50s"})],
        capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except Exception:
        print(f"  ! {label}: bad response {r.stdout[:200]} {r.stderr[:200]}"); sys.exit(1)
    sid = d.get("statement_id")
    state = (d.get("status") or {}).get("state", "")
    while state in ("PENDING", "RUNNING") and sid:
        time.sleep(4)
        g = subprocess.run(["databricks", "api", "get", f"/api/2.0/sql/statements/{sid}", "-p", PROFILE],
                           capture_output=True, text=True)
        try:
            d = json.loads(g.stdout)
            state = (d.get("status") or {}).get("state", "")
        except Exception:
            state = ""
    if state != "SUCCEEDED":
        err = (d.get("status") or {}).get("error", {})
        print(f"  ! {label}: {state} {json.dumps(err)[:400]}"); sys.exit(1)
    print(f"  ok {label} ({round(time.time()-t0)}s)", flush=True)


def run_target_file(path: str) -> None:
    import re
    raw = open(path).read()
    no_comments = "\n".join(re.sub(r"--.*$", "", line) for line in raw.splitlines())
    for i, stmt in enumerate(s.strip() for s in no_comments.split(";")):
        if stmt:
            sql(stmt, f"{os.path.basename(path)} stmt#{i+1}")


def build_source() -> None:
    sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{SRC}", f"schema {SRC}")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{SRC}._raw AS
SELECT id AS order_id,
  timestamp'2023-01-01 00:00:00' + make_interval(0,0,0, CAST(id%730 AS INT), CAST(id%24 AS INT),0,0) AS order_ts,
  date_add(DATE'2023-01-01', CAST(id%730 AS INT)) AS order_dt,
  CAST(id%20000 AS INT) AS customer_id, CAST(id%2000 AS INT) AS product_id, CAST(id%50 AS INT) AS store_id,
  CAST(1 + id%10 AS INT) AS quantity,
  CAST(5 + (id%500) + (id%13)/13.0 AS DECIMAL(18,4)) AS unit_price,
  CAST((id%30)/100.0 AS DECIMAL(9,4)) AS discount_pct,
  CAST((id%20)/100.0 AS DECIMAL(9,4)) AS tax_rate,
  element_at({ARR_CUR}, CAST(id%5 AS INT)+1) AS currency,
  element_at({ARR_STATUS}, CAST(id%4 AS INT)+1) AS status_code,
  concat('  ', element_at({ARR_ORG}, CAST(id%5 AS INT)+1), '_', CAST(id%20000 AS STRING), '  ') AS customer_name_raw,
  CASE WHEN id%2=0 THEN 'Y' ELSE 'N' END AS is_active_raw
FROM range({N})""", f"{SRC}._raw ({N:,} rows)")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{SRC}.dim_fx AS
SELECT c.currency, d.fx_date,
  CAST(c.base * (1 + (day(d.fx_date)-1)*0.001) AS DECIMAL(12,6)) AS rate_to_usd
FROM (VALUES ('USD',CAST(1.0 AS DOUBLE)),('EUR',1.08),('GBP',1.27),('JPY',0.0068),('INR',0.012)) c(currency,base)
CROSS JOIN (SELECT date_add(DATE'2023-01-01', CAST(id AS INT)) AS fx_date FROM range(731)) d""", f"{SRC}.dim_fx")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{SRC}._raw_customer AS
SELECT id AS customer_id,
  concat('  ', element_at({ARR_PERSON}, CAST(id%5 AS INT)+1), ' ', CAST(id AS STRING), '  ') AS customer_name,
  concat('User', CAST(id AS STRING), '@Example.COM') AS email,
  element_at(array('Consumer','SMB','Enterprise'), CAST(id%3 AS INT)+1) AS segment,
  element_at(array('US','UK','DE','JP','IN'), CAST(id%5 AS INT)+1) AS country,
  CASE WHEN id%3=0 THEN 'N' ELSE 'Y' END AS is_active_raw
FROM range(20000)""", f"{SRC}._raw_customer")

    # SOURCE gold — the correct EDW logic (ground truth).
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{SRC}.fact_sales AS
SELECT r.order_id, r.order_ts AS order_ts_utc, r.customer_id, r.product_id, r.store_id, r.quantity,
  r.unit_price, r.discount_pct, r.tax_rate, r.currency, r.status_code,
  initcap(trim(r.customer_name_raw)) AS customer_name,
  (r.is_active_raw='Y') AS is_active,
  ROUND(r.quantity*r.unit_price*(1-r.discount_pct)*(1+r.tax_rate), 4) AS net_revenue,
  ROUND(r.quantity*r.unit_price*fx.rate_to_usd, 2) AS amount_usd,
  CASE r.status_code WHEN 'A' THEN 'Active' WHEN 'C' THEN 'Closed' WHEN 'P' THEN 'Pending'
                     WHEN 'R' THEN 'Returned' ELSE 'Unknown' END AS status_bucket
FROM {CAT}.{SRC}._raw r
LEFT JOIN {CAT}.{SRC}.dim_fx fx ON fx.currency=r.currency AND fx.fx_date=r.order_dt""",
        f"{SRC}.fact_sales (source gold)")

    # SOURCE dim_customer — with a genuine, source-side segment reclassification on a small
    # slice (a real re-tiering the target snapshot predates -> genuine upstream data, not code).
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{SRC}.dim_customer AS
SELECT c.customer_id, initcap(trim(c.customer_name)) AS customer_name, lower(c.email) AS email,
  CASE WHEN c.customer_id % 137 = 0 THEN 'Enterprise' ELSE c.segment END AS segment,
  c.country, (c.is_active_raw='Y') AS is_active
FROM {CAT}.{SRC}._raw_customer c""", f"{SRC}.dim_customer (source gold)")


def build_target() -> None:
    sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{TGT}", f"schema {TGT}")
    run_target_file(os.path.join(HERE, "revenue_target.sql"))


# ------- reconcile -------
TABLES = [
    {"source_name": "fact_sales", "target_name": "fact_sales", "join_columns": ["order_id"],
     "column_thresholds": [
         {"column_name": "tax_rate", "lower_bound": "-0.01", "upper_bound": "0.01", "type": "decimal"}]},
    {"source_name": "dim_customer", "target_name": "dim_customer", "join_columns": ["customer_id"]},
]


def ycfg():
    return f"""metadata_config:
  catalog: {CAT}
  schema: reconcile
  volume: reconcile_volume
report_type: all
source:
  dialect: databricks
  catalog: {CAT}
  schema: {SRC}
target:
  catalog: {CAT}
  schema: {TGT}
version: 2
"""


def put(name, body):
    p = f"/tmp/{name}"
    open(p, "w").write(body)
    subprocess.run(["databricks", "workspace", "import", f"{LB}/{name}", "--file", p,
                    "--format", "AUTO", "--overwrite", "-p", PROFILE], capture_output=True)


def run_reconcile():
    put("reconcile.yml", ycfg())
    put(f"recon_config_databricks_{CAT}_all.json", json.dumps({"tables": TABLES}, indent=2))
    t0 = time.time()
    out = subprocess.run(["databricks", "labs", "lakebridge", "reconcile"], input="\n",
                         capture_output=True, text=True, env=ENV).stderr
    rid = next((l.split("runs/")[1].split("`")[0].split()[0].strip()
                for l in out.splitlines() if "runs/" in l), None)
    print(f"  reconcile job run: {rid}", flush=True)
    while rid:
        r = subprocess.run(["databricks", "jobs", "get-run", rid, "-p", PROFILE, "-o", "json"],
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


def latest_recon_ids():
    q = (f"SELECT operation_name, recon_id FROM {CAT}.reconcile.main "
         f"WHERE target_table.schema='{TGT}' "
         f"QUALIFY row_number() OVER (PARTITION BY operation_name ORDER BY recon_table_id DESC)=1")
    r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
                        json.dumps({"warehouse_id": WH, "statement": q, "wait_timeout": "40s"})],
                       capture_output=True, text=True)
    try:
        rows = json.loads(r.stdout).get("result", {}).get("data_array") or []
        return {op: rid for op, rid in rows}
    except Exception:
        return {}


if __name__ == "__main__":
    print(f"[REVENUE] building source {SRC} ({N:,} fact rows) ...", flush=True)
    build_source()
    print(f"[REVENUE] building target {TGT} (revenue_target.sql) ...", flush=True)
    build_target()
    print("[REVENUE] running Lakebridge reconcile ...", flush=True)
    run_reconcile()
    ids = latest_recon_ids()
    print(f"[REVENUE] RECON_IDS={json.dumps(ids)}", flush=True)
