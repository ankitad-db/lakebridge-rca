-- PILOT TARGET (Databricks) — mig_target.agg_daily_sales   [migrated from RETAIL.SOURCE.AGG_DAILY_SALES]
-- DEFECT S5 (transpilation): REVENUE rounded to whole units (half-even) instead of the source's
-- exact NUMBER(18,2) SUM -- mirrors a ROUND rounding-mode difference between Snowflake and Spark.

CREATE TABLE IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_target.agg_daily_sales (
  store_id    BIGINT        COMMENT 'FK to dim_store',
  sales_date  DATE          COMMENT 'Sales date',
  revenue     DECIMAL(18,2) COMMENT 'Daily revenue',
  order_count BIGINT        COMMENT 'Daily order count'
) CLUSTER BY (store_id, sales_date)
COMMENT 'Gold daily sales aggregate (migrated)';

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.agg_daily_sales
SELECT
  store_id,
  CAST(order_ts AS DATE)                        AS sales_date,
  CAST(round(sum(order_total), 0) AS DECIMAL(18,2)) AS revenue,   -- S5: round to whole units
  count(*)                                      AS order_count
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_orders
GROUP BY store_id, CAST(order_ts AS DATE);
