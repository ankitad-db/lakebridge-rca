# Databricks notebook source
# MAGIC %md
# MAGIC # Incremental merge (idempotent upsert)
# MAGIC Best-practice incremental load for `fact_orders` using a watermark and a
# MAGIC MERGE so re-runs are idempotent. The intentional migration defect S6
# MAGIC (watermark lag dropping late-arriving orders) is modeled by a watermark
# MAGIC that excludes `order_id > 480`.

# COMMAND ----------
dbutils.widgets.text("source_catalog", "fevm_ps_dr_us_east_2_catalog")
dbutils.widgets.text("source_schema", "mig_source_sim")
dbutils.widgets.text("target_catalog", "fevm_ps_dr_us_east_2_catalog")
dbutils.widgets.text("target_schema", "mig_target")
dbutils.widgets.text("watermark_order_id", "480")

SRC = f"{dbutils.widgets.get('source_catalog')}.{dbutils.widgets.get('source_schema')}"
TGT = f"{dbutils.widgets.get('target_catalog')}.{dbutils.widgets.get('target_schema')}"
WATERMARK = int(dbutils.widgets.get("watermark_order_id"))

# COMMAND ----------
# Incremental slice bounded by the watermark. A correct pipeline would advance
# the watermark to include late data; here it lags, which is defect S6.
spark.sql(f"""
    MERGE INTO {TGT}.fact_orders t
    USING (
        SELECT order_id, customer_id, store_id,
               order_ts + INTERVAL 5 HOURS 30 MINUTES AS order_ts,
               status, order_total
        FROM {SRC}.fact_orders
        WHERE order_id <= {WATERMARK}
    ) s
    ON t.order_id = s.order_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")
print("fact_orders merge complete")
