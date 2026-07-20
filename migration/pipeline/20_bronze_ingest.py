# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze ingest
# MAGIC Raw ingest of the source tables into the bronze layer, preserving source
# MAGIC values exactly (no transformation). In a real migration this is where you
# MAGIC land Snowflake extracts (e.g. via Lakehouse Federation, COPY INTO, or a
# MAGIC connector). Here the "source" is the `mig_source_sim` schema.

# COMMAND ----------
from pyspark.sql.functions import current_timestamp

dbutils.widgets.text("source_catalog", "fevm_ps_dr_us_east_2_catalog")
dbutils.widgets.text("source_schema", "mig_source_sim")
dbutils.widgets.text("bronze_catalog", "fevm_ps_dr_us_east_2_catalog")
dbutils.widgets.text("bronze_schema", "mig_bronze")

SRC = f"{dbutils.widgets.get('source_catalog')}.{dbutils.widgets.get('source_schema')}"
BRZ = f"{dbutils.widgets.get('bronze_catalog')}.{dbutils.widgets.get('bronze_schema')}"

# COMMAND ----------
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {BRZ}")

TABLES = ["dim_store", "dim_product", "dim_customer", "fact_orders", "fact_order_items"]

# COMMAND ----------
# Best practice: idempotent full refresh for dimensions/small facts; add an
# ingest_ts audit column. Values are copied verbatim (bronze = raw).
for t in TABLES:
    (spark.table(f"{SRC}.{t}")
        .withColumn("_ingest_ts", current_timestamp())
        .write.mode("overwrite").option("overwriteSchema", "true")
        .saveAsTable(f"{BRZ}.{t}"))
    print(f"ingested {BRZ}.{t}")
