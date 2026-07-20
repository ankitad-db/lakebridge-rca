-- Silver transform: load the migrated dimensions and facts from the source.
-- This is where several migration defects are (realistically) introduced.
-- Run after target/10_target_ddl.sql.
--
-- Source: fevm_ps_dr_us_east_2_catalog.mig_source_sim
-- Target: fevm_ps_dr_us_east_2_catalog.mig_target

-- dim_store: clean copy (no defect) --------------------------------------------
INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.dim_store
SELECT store_id, store_name, region, store_tz
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_store;

-- dim_product: S4 STRING_FORMAT -> sku lower-cased with trailing whitespace ----
INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.dim_product
SELECT product_id, concat(lower(sku), '  ') AS sku, product_name, category, unit_price
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_product;

-- dim_customer: multiple defects ----------------------------------------------
--   S3 SEMI_STRUCTURED: attributes JSON keys reordered (semantically equal -> benign)
--   S8 UPSTREAM_DRIFT:  marketing_segment stale for every 25th customer; older updated_ts
--   S9 NULL_BOOLEAN:    is_active 'Y'/'N' -> 'true'/'false'; email NULL -> '' (empty string)
--   S10 GENUINE_DATA:   loyalty_tier populated in target though source is NULL
INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.dim_customer
SELECT
  customer_id,
  customer_name,
  coalesce(email, '') AS email,
  concat('{"channel":"', get_json_object(attributes, '$.channel'),
         '","segment":"', get_json_object(attributes, '$.segment'), '"}') AS attributes,
  CASE WHEN is_active = 'Y' THEN 'true' ELSE 'false' END AS is_active,
  element_at(array('Bronze','Silver','Gold'), cast((customer_id % 3) + 1 AS INT)) AS loyalty_tier,
  CASE WHEN customer_id % 25 = 0 THEN 'STALE' ELSE marketing_segment END AS marketing_segment,
  cast(date_sub(current_date(), 10) AS TIMESTAMP) AS updated_ts
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_customer;

-- fact_orders: S2 TIMEZONE (+5:30 offset, no UTC normalization)
--              S6 VOLUME_MISSING (watermark drops order_id > 480) --------------
INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.fact_orders
SELECT
  order_id, customer_id, store_id,
  order_ts + make_interval(0, 0, 0, 0, 5, 30, 0) AS order_ts,
  status, order_total
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_orders
WHERE order_id <= 480;

-- fact_order_items: S1 TYPE_PRECISION (amount 4dp -> 2dp)
--                   S7 VOLUME_EXTRA (fan-out duplicates for order_id <= 5) ------
INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.fact_order_items
SELECT order_item_id, order_id, product_id, qty,
       cast(amount AS DECIMAL(18,2)) AS amount, discount
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_order_items
UNION ALL
SELECT order_item_id + 1000000 AS order_item_id, order_id, product_id, qty,
       cast(amount AS DECIMAL(18,2)) AS amount, discount
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_order_items
WHERE order_id <= 5;
