-- Simulated Snowflake source for the migration RCA test bed.
-- Represents the "correct" source-of-truth data as it exists in Snowflake.
-- Namespaces are schema-based inside an existing catalog (catalog creation on
-- this workspace requires a managed location / UI Default Storage).
--
-- Catalog: fevm_ps_dr_us_east_2_catalog   Schema: mig_source_sim

CREATE SCHEMA IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_source_sim
  COMMENT 'Simulated Snowflake source for migration RCA test bed';

-- ---------------------------------------------------------------------------
-- dim_store (5 stores, each with a timezone)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_store AS
SELECT
  id AS store_id,
  concat('Store_', id) AS store_name,
  element_at(array('APAC','EMEA','AMER','APAC','EMEA'), cast(id AS INT)) AS region,
  element_at(array('Asia/Kolkata','Europe/London','America/New_York','Asia/Singapore','Europe/Paris'), cast(id AS INT)) AS store_tz
FROM range(1, 6) AS t(id);

-- ---------------------------------------------------------------------------
-- dim_product (30 products) - unit_price kept as DECIMAL(18,4)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_product AS
SELECT
  id AS product_id,
  concat('SKU-', lpad(cast(id AS STRING), 4, '0')) AS sku,
  concat('Product ', id) AS product_name,
  element_at(array('Electronics','Home','Grocery','Apparel','Toys'), cast((id % 5) + 1 AS INT)) AS category,
  cast(round(10 + id * 3.25, 4) AS DECIMAL(18,4)) AS unit_price
FROM range(1, 31) AS t(id);

-- ---------------------------------------------------------------------------
-- dim_customer (100 customers)
--   loyalty_tier is intentionally NULL in source (never populated).
--   email is NULL for every 20th customer.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_customer AS
SELECT
  id AS customer_id,
  concat('Customer_', id) AS customer_name,
  CASE WHEN id % 20 = 0 THEN NULL ELSE concat('cust', id, '@example.com') END AS email,
  concat('{"segment":"', element_at(array('A','B','C'), cast((id % 3) + 1 AS INT)),
         '","channel":"', element_at(array('web','store','mobile'), cast((id % 3) + 1 AS INT)), '"}') AS attributes,
  CASE WHEN id % 7 = 0 THEN 'N' ELSE 'Y' END AS is_active,
  CAST(NULL AS STRING) AS loyalty_tier,
  element_at(array('A','B','C'), cast((id % 3) + 1 AS INT)) AS marketing_segment,
  current_timestamp() AS updated_ts
FROM range(1, 101) AS t(id);

-- ---------------------------------------------------------------------------
-- fact_orders (500 orders)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_orders AS
SELECT
  id AS order_id,
  cast((id % 100) + 1 AS BIGINT) AS customer_id,
  cast((id % 5) + 1 AS BIGINT) AS store_id,
  cast(date_sub(current_date(), cast(id % 60 AS INT)) AS TIMESTAMP)
    + make_interval(0, 0, 0, 0, cast(id % 24 AS INT), cast(id % 60 AS INT), 0) AS order_ts,
  element_at(array('COMPLETED','SHIPPED','PENDING','RETURNED'), cast((id % 4) + 1 AS INT)) AS status,
  cast(round(20 + (id % 500) * 1.7777, 4) AS DECIMAL(18,4)) AS order_total
FROM range(1, 501) AS t(id);

-- ---------------------------------------------------------------------------
-- fact_order_items (3 items per order = 1500 rows) - amount at DECIMAL(18,4)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_order_items AS
SELECT
  (o.order_id * 10 + s.k) AS order_item_id,
  o.order_id,
  cast(((o.order_id + s.k) % 30) + 1 AS BIGINT) AS product_id,
  cast(s.k + 1 AS INT) AS qty,
  cast(round(((o.order_id + s.k) % 200) * 1.2345 + 0.6789, 4) AS DECIMAL(18,4)) AS amount,
  cast(round(s.k * 0.05, 4) AS DECIMAL(18,4)) AS discount
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_orders o
LATERAL VIEW explode(array(0, 1, 2)) s AS k;

-- ---------------------------------------------------------------------------
-- gold: agg_daily_sales (daily revenue per store) - the "correct" aggregate
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.agg_daily_sales AS
SELECT
  store_id,
  cast(order_ts AS DATE) AS sales_date,
  cast(sum(order_total) AS DECIMAL(18,2)) AS revenue,
  count(*) AS order_count
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_orders
GROUP BY store_id, cast(order_ts AS DATE);
