"""Prod-volume benchmark bed: WIDE, high-cardinality retail fact at ~50M rows.

Answers "does it survive real prod volume?" — genuine GB (not compressed MB), same seeded
defects so RCA still root-causes. Builds mig_xl_src/tgt, runs Lakebridge reconcile, prints
the recon_id + DESCRIBE DETAIL sizes. Run in background:
    python3 migration/retail_demo/build_xl_bed.py
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
N = 50_000_000
SRC, TGT = "mig_xl_src", "mig_xl_tgt"
HERE = os.path.dirname(os.path.abspath(__file__))


def sql(stmt, label="", timeout=1800):
    t0 = time.time()
    r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
                        json.dumps({"warehouse_id": WH, "statement": stmt, "wait_timeout": "50s"})],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except Exception:
        print(f"  ! {label}: {r.stdout[:200]}{r.stderr[:200]}"); return False
    sid = d.get("statement_id"); state = (d.get("status") or {}).get("state", "")
    while state in ("PENDING", "RUNNING") and sid and time.time() - t0 < timeout:
        time.sleep(6)
        g = subprocess.run(["databricks", "api", "get", f"/api/2.0/sql/statements/{sid}", "-p", PROFILE],
                           capture_output=True, text=True)
        try:
            state = (json.loads(g.stdout).get("status") or {}).get("state", "")
        except Exception:
            state = ""
    ok = state == "SUCCEEDED"
    print(f"  {'ok' if ok else '! '+state} {label} ({round(time.time()-t0)}s)", flush=True)
    if not ok:
        print("     ", json.dumps((d.get('status') or {}).get('error', {}))[:300])
    return ok


# ~10 high-cardinality filler columns (identical in src & tgt) to make size genuine GB.
FILLERS = """
  uuid() AS uid, uuid() AS uid2,
  sha2(concat(cast(id AS string), cast(rand() AS string)), 256) AS txn_hash,
  md5(cast(id*13+7 AS string)) AS ext_id,
  concat(uuid(), '-', uuid()) AS note,
  CAST(rand()*180-90 AS DECIMAL(9,6)) AS lat,
  CAST(rand()*360-180 AS DECIMAL(9,6)) AS lon,
  CAST(rand()*1000000 AS DECIMAL(18,4)) AS score,
  CAST(rand()*1e9 AS DECIMAL(18,4)) AS m1,
  CAST(rand()*1e9 AS DECIMAL(18,4)) AS m2
""".strip()
FILLER_COLS = "uid, uid2, txn_hash, ext_id, note, lat, lon, score, m1, m2"

# The buggy target ETL (same defects as the hybrid retail bed) — written to a .sql artifact
# for code-aware RCA and executed to build the target.
TGT_SQL = f"""CREATE OR REPLACE TABLE {CAT}.{TGT}.fact_sales AS
SELECT r.order_id,
  r.order_ts + INTERVAL 5 HOURS AS order_ts_utc,
  r.customer_id, r.product_id, r.store_id, r.quantity,
  CAST(ROUND(r.unit_price, 2) AS DECIMAL(18,2)) AS unit_price,
  r.discount_pct, r.tax_rate, r.currency, r.status_code,
  UPPER(TRIM(r.customer_name_raw)) AS customer_name,
  (r.is_active_raw = 'Y') AS is_active,
  ROUND(r.quantity*r.unit_price*(1 + r.tax_rate) - r.quantity*r.unit_price*r.discount_pct, 4) AS net_revenue,
  ROUND(r.quantity*r.unit_price*fx.rate_to_usd, 2) AS amount_usd,
  CASE r.status_code WHEN 'A' THEN 'Active' WHEN 'C' THEN 'Closed' WHEN 'P' THEN 'Pending' ELSE 'Unknown' END AS status_bucket,
  {FILLER_COLS}
FROM {CAT}.{SRC}._raw r
LEFT JOIN {CAT}.{SRC}.dim_fx fx ON fx.currency=r.currency AND fx.fx_date=trunc(r.order_dt,'MM')
WHERE r.order_id % 500 <> 0"""


def build():
    sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{SRC}", "schema src")
    sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{TGT}", "schema tgt")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{SRC}.dim_fx AS
SELECT c.currency, d.fx_date, CAST(c.base*(1+(day(d.fx_date)-1)*0.001) AS DECIMAL(12,6)) AS rate_to_usd
FROM (VALUES ('USD',CAST(1.0 AS DOUBLE)),('EUR',1.08),('GBP',1.27),('JPY',0.0068),('INR',0.012)) c(currency,base)
CROSS JOIN (SELECT date_add(DATE'2023-01-01', CAST(id AS INT)) AS fx_date FROM range(731)) d""", "dim_fx")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{SRC}._raw AS
SELECT id AS order_id,
  timestamp'2023-01-01 00:00:00' + make_interval(0,0,0,CAST(id%730 AS INT),CAST(id%24 AS INT),0,0) AS order_ts,
  date_add(DATE'2023-01-01', CAST(id%730 AS INT)) AS order_dt,
  CAST(id%2000000 AS INT) AS customer_id, CAST(id%50000 AS INT) AS product_id, CAST(id%500 AS INT) AS store_id,
  CAST(1+id%10 AS INT) AS quantity,
  CAST(5+(id%500)+(id%13)/13.0 AS DECIMAL(18,4)) AS unit_price,
  CAST((id%30)/100.0 AS DECIMAL(9,4)) AS discount_pct,
  CAST((id%20)/100.0 AS DECIMAL(9,4)) AS tax_rate,
  element_at(array('USD','EUR','GBP','JPY','INR'), CAST(id%5 AS INT)+1) AS currency,
  element_at(array('A','C','P','R'), CAST(id%4 AS INT)+1) AS status_code,
  concat('  ', element_at(array('Acme','Globex','Initech','Umbrella','Soylent'), CAST(id%5 AS INT)+1), '_', CAST(id%2000000 AS STRING), '  ') AS customer_name_raw,
  CASE WHEN id%2=0 THEN 'Y' ELSE 'N' END AS is_active_raw,
  {FILLERS}
FROM range({N})""", f"_raw {N:,} rows")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{SRC}.fact_sales AS
SELECT r.order_id, r.order_ts AS order_ts_utc, r.customer_id, r.product_id, r.store_id, r.quantity,
  r.unit_price, r.discount_pct, r.tax_rate, r.currency, r.status_code,
  initcap(trim(r.customer_name_raw)) AS customer_name, (r.is_active_raw='Y') AS is_active,
  ROUND(r.quantity*r.unit_price*(1-r.discount_pct)*(1+r.tax_rate), 4) AS net_revenue,
  ROUND(r.quantity*r.unit_price*fx.rate_to_usd, 2) AS amount_usd,
  CASE r.status_code WHEN 'A' THEN 'Active' WHEN 'C' THEN 'Closed' WHEN 'P' THEN 'Pending' WHEN 'R' THEN 'Returned' ELSE 'Unknown' END AS status_bucket,
  {FILLER_COLS}
FROM {CAT}.{SRC}._raw r
LEFT JOIN {CAT}.{SRC}.dim_fx fx ON fx.currency=r.currency AND fx.fx_date=r.order_dt""", "src.fact_sales (correct)")
    open(os.path.join(HERE, "xl_target.sql"), "w").write(TGT_SQL + ";\n")
    sql(TGT_SQL, "tgt.fact_sales (buggy artifact)")


def sizes():
    for t in (f"{SRC}.fact_sales", f"{TGT}.fact_sales"):
        r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
                            json.dumps({"warehouse_id": WH, "statement": f"DESCRIBE DETAIL {CAT}.{t}", "wait_timeout": "40s"})],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout); cols = [c["name"] for c in d["manifest"]["schema"]["columns"]]
            row = dict(zip(cols, d["result"]["data_array"][0]))
            print(f"  {t}: {int(row.get('sizeInBytes',0))/1e9:.2f} GB stored · {row.get('numFiles')} files", flush=True)
        except Exception as e:
            print(f"  {t}: size err {str(e)[:120]}")


def reconcile():
    ycfg = f"""metadata_config:
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
    tcfg = {"tables": [{"source_name": "fact_sales", "target_name": "fact_sales", "join_columns": ["order_id"]}]}
    for name, body in [("reconcile.yml", ycfg), (f"recon_config_databricks_{CAT}_all.json", json.dumps(tcfg, indent=2))]:
        p = f"/tmp/{name}"; open(p, "w").write(body)
        subprocess.run(["databricks", "workspace", "import", f"{LB}/{name}", "--file", p, "--format", "AUTO",
                        "--overwrite", "-p", PROFILE], capture_output=True)
    t0 = time.time()
    out = subprocess.run(["databricks", "labs", "lakebridge", "reconcile"], input="\n",
                        capture_output=True, text=True, env=ENV).stderr
    rid = next((l.split("runs/")[1].split("`")[0].split()[0].strip() for l in out.splitlines() if "runs/" in l), None)
    print(f"  reconcile job run: {rid}", flush=True)
    while rid:
        r = subprocess.run(["databricks", "jobs", "get-run", rid, "-p", PROFILE, "-o", "json"], capture_output=True, text=True)
        try:
            st = (json.loads(r.stdout).get("status") or {}).get("state", "")
        except Exception:
            st = ""
        if st in ("TERMINATED", "INTERNAL_ERROR"):
            code = (json.loads(r.stdout).get("status", {}).get("termination_details") or {}).get("code", "")
            print(f"  reconcile: {code} in {round(time.time()-t0)}s", flush=True); break
        time.sleep(15)
    q = f"SELECT recon_id FROM {CAT}.reconcile.main WHERE target_table.schema='{TGT}' ORDER BY recon_table_id DESC LIMIT 1"
    r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
                        json.dumps({"warehouse_id": WH, "statement": q, "wait_timeout": "40s"})], capture_output=True, text=True)
    try:
        rows = json.loads(r.stdout).get("result", {}).get("data_array") or []
        print("XL_RECON_ID=" + (rows[0][0] if rows else "none"), flush=True)
    except Exception as e:
        print("recon_id err", str(e)[:120])


if __name__ == "__main__":
    print(f"Building XL bed ({N:,} wide rows) ...", flush=True)
    build()
    print("Sizes:", flush=True); sizes()
    print("Reconciling ...", flush=True); reconcile()
    print("DONE.", flush=True)
