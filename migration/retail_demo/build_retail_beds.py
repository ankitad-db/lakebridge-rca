"""Build the two retail demo beds (HYBRID + DETERMINISTIC) on ps-dr-east.

For each bed:
  * <src>._raw / _raw_customer / _raw_product  -- landed raw extract (shared input)
  * <src>.dim_fx                               -- daily FX rates (drift within month)
  * <src>.fact_sales / dim_customer / dim_product  -- SOURCE gold (correct EDW logic)
  * <tgt>.*  built by the target ETL .sql files (the migrated, defect-carrying logic)

Source = ground truth (correct, full). Target = migrated (defects). Reconcile compares them.
Run:  python migration/retail_demo/build_retail_beds.py
"""
import json
import os
import subprocess
import sys
import time

CAT = "fevm_ps_dr_us_east_2_catalog"
WH = "3220376d4497e2d7"
PROFILE = "ps-dr-east"
N = 2_000_000
HERE = os.path.dirname(os.path.abspath(__file__))


def sql(stmt: str, label: str = "") -> None:
    """Submit a SQL statement and poll to completion."""
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
            state = (json.loads(g.stdout).get("status") or {}).get("state", "")
        except Exception:
            state = ""
    if state != "SUCCEEDED":
        err = (d.get("status") or {}).get("error", {})
        print(f"  ! {label}: {state} {json.dumps(err)[:400]}"); sys.exit(1)
    print(f"  ok {label} ({round(time.time()-t0)}s)")


def run_target_file(path: str) -> None:
    import re
    raw = open(path).read()
    # strip line comments FIRST so semicolons inside comments don't split statements
    no_comments = "\n".join(re.sub(r"--.*$", "", line) for line in raw.splitlines())
    for i, stmt in enumerate(s.strip() for s in no_comments.split(";")):
        if stmt:
            sql(stmt, f"{os.path.basename(path)} stmt#{i+1}")


ARR_CUR = "array('USD','EUR','GBP','JPY','INR')"
ARR_STATUS = "array('A','C','P','R')"
ARR_ORG = "array('Acme','Globex','Initech','Umbrella','Soylent')"
ARR_PERSON = "array('John Smith','Mary Jones','Wei Chen','Ana Silva','Omar Farah')"
ARR_PROD = "array('Widget','Gadget','Gizmo','Doohickey','Sprocket')"
ARR_CATEG = "array('Electronics','Home','Sports','Toys','Grocery')"


def raw_tables(src: str) -> None:
    sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.{src}", f"schema {src}")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{src}._raw AS
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
FROM range({N})""", f"{src}._raw")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{src}.dim_fx AS
SELECT c.currency, d.fx_date,
  CAST(c.base * (1 + (day(d.fx_date)-1)*0.001) AS DECIMAL(12,6)) AS rate_to_usd
FROM (VALUES ('USD',CAST(1.0 AS DOUBLE)),('EUR',1.08),('GBP',1.27),('JPY',0.0068),('INR',0.012)) c(currency,base)
CROSS JOIN (SELECT date_add(DATE'2023-01-01', CAST(id AS INT)) AS fx_date FROM range(731)) d""", f"{src}.dim_fx")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{src}._raw_customer AS
SELECT id AS customer_id,
  concat('  ', element_at({ARR_PERSON}, CAST(id%5 AS INT)+1), ' ', CAST(id AS STRING), '  ') AS customer_name,
  concat('User', CAST(id AS STRING), '@Example.COM') AS email,
  element_at(array('Consumer','SMB','Enterprise'), CAST(id%3 AS INT)+1) AS segment,
  element_at(array('US','UK','DE','JP','IN'), CAST(id%5 AS INT)+1) AS country,
  CASE WHEN id%3=0 THEN 'N' ELSE 'Y' END AS is_active_raw,
  CAST((id%20)*750 AS DECIMAL(18,2)) AS lifetime_spend
FROM range(20000)""", f"{src}._raw_customer")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{src}._raw_product AS
SELECT id AS product_id,
  concat('  ', element_at({ARR_PROD}, CAST(id%5 AS INT)+1), ' ', CAST(id AS STRING), '  ') AS product_name,
  element_at({ARR_CATEG}, CAST(id%5 AS INT)+1) AS category,
  element_at(array('A','B','C'), CAST(id%3 AS INT)+1) AS subcategory,
  CAST(10 + (id%990) + (id%7)/7.0 + (id%11)/110.0 AS DECIMAL(18,4)) AS list_price
FROM range(2000)""", f"{src}._raw_product")


def source_gold(src: str, hybrid: bool) -> None:
    is_active = "(r.is_active_raw='Y')" if hybrid else "r.is_active_raw"
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{src}.fact_sales AS
SELECT r.order_id, r.order_ts AS order_ts_utc, r.customer_id, r.product_id, r.store_id, r.quantity,
  r.unit_price, r.discount_pct, r.tax_rate, r.currency, r.status_code,
  initcap(trim(r.customer_name_raw)) AS customer_name,
  {is_active} AS is_active,
  ROUND(r.quantity*r.unit_price*(1-r.discount_pct)*(1+r.tax_rate), 4) AS net_revenue,
  ROUND(r.quantity*r.unit_price*fx.rate_to_usd, 2) AS amount_usd,
  CASE r.status_code WHEN 'A' THEN 'Active' WHEN 'C' THEN 'Closed' WHEN 'P' THEN 'Pending'
                     WHEN 'R' THEN 'Returned' ELSE 'Unknown' END AS status_bucket
FROM {CAT}.{src}._raw r
LEFT JOIN {CAT}.{src}.dim_fx fx ON fx.currency=r.currency AND fx.fx_date=r.order_dt""", f"{src}.fact_sales (source)")

    cust_active = "(c.is_active_raw='Y')" if hybrid else "c.is_active_raw"
    loyalty = (",\n  CASE WHEN c.lifetime_spend >= 10000 THEN 'PLATINUM' WHEN c.lifetime_spend >= 1000 "
               "THEN 'GOLD' ELSE 'STANDARD' END AS loyalty_tier") if hybrid else ""
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{src}.dim_customer AS
SELECT c.customer_id, initcap(trim(c.customer_name)) AS customer_name, c.email, c.segment, c.country,
  {cust_active} AS is_active{loyalty}
FROM {CAT}.{src}._raw_customer c""", f"{src}.dim_customer (source)")

    # hybrid source omits 'hue' -> target adds it (semi_structured defect); det matches target.
    attrs = ("to_json(named_struct('sku', concat('SKU-', CAST(p.product_id AS STRING)), "
             "'tier', CASE WHEN p.list_price > 100 THEN 'A' ELSE 'B' END))") if hybrid else \
            ("to_json(named_struct('sku', concat('SKU-', CAST(p.product_id AS STRING)), "
             "'tier', CASE WHEN p.list_price > 100 THEN 'A' ELSE 'B' END))")
    sql(f"""CREATE OR REPLACE TABLE {CAT}.{src}.dim_product AS
SELECT p.product_id, initcap(trim(p.product_name)) AS product_name, p.category, p.subcategory,
  p.list_price, concat_ws(' > ', p.category, p.subcategory) AS category_path,
  {attrs} AS attrs
FROM {CAT}.{src}._raw_product p""", f"{src}.dim_product (source)")


def main():
    print(f"Building HYBRID bed (mig_hyb_src/tgt), {N:,} fact rows ...")
    raw_tables("mig_hyb_src")
    source_gold("mig_hyb_src", hybrid=True)
    sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.mig_hyb_tgt", "schema mig_hyb_tgt")
    run_target_file(os.path.join(HERE, "hybrid_target.sql"))

    print(f"Building DETERMINISTIC bed (mig_det_src/tgt), {N:,} fact rows ...")
    raw_tables("mig_det_src")
    source_gold("mig_det_src", hybrid=False)
    sql(f"CREATE SCHEMA IF NOT EXISTS {CAT}.mig_det_tgt", "schema mig_det_tgt")
    run_target_file(os.path.join(HERE, "det_target.sql"))
    print("DONE. Beds built: mig_hyb_src/tgt, mig_det_src/tgt.")


if __name__ == "__main__":
    main()
