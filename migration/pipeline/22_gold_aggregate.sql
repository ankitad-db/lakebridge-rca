-- Gold aggregate: daily sales per store.
-- S5 TRANSPILATION: revenue rounded to whole units (half-even) instead of the
-- source's DECIMAL(18,2) sum -- mirrors a ROUND rounding-mode difference between
-- Snowflake and Spark. Built from the source facts so the defect is isolated to
-- the aggregation logic (same daily grain as source, so rows align 1:1).
--
-- Run after source_sim is populated and target/10_target_ddl.sql has run.

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.agg_daily_sales
SELECT
  store_id,
  cast(order_ts AS DATE) AS sales_date,
  cast(round(sum(order_total), 0) AS DECIMAL(18,2)) AS revenue,
  count(*) AS order_count
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_orders
GROUP BY store_id, cast(order_ts AS DATE);
