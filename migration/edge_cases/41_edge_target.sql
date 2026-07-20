-- Edge-case TARGET (migrated) tables with the injected defects. CTAS is used so
-- each table's schema follows the transform (e.g. DOUBLE, renamed column), which
-- is itself part of some scenarios (E4 schema). Run after 40_edge_source.sql.
--
-- Each defect is annotated with its scenario id (see migration/scenarios.yaml).
-- Catalog: fevm_ps_dr_us_east_2_catalog   Schema: mig_target

-- E1 DECIMAL(18,6) -> DOUBLE (binary float error) ; E2 BIGINT -> INT wrap -------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.edge_numeric AS
SELECT
  rid,
  cast(v_double AS DOUBLE) AS v_double,
  (((big_id + 2147483648) % 4294967296) - 2147483648) AS big_id   -- deterministic 32-bit wrap
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.edge_numeric;

-- E3 non-constant offset (varies by row -> NOT a single tz normalization) -------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.edge_events AS
SELECT
  eid,
  event_ts + make_interval(0, 0, 0, 0, cast((eid % 3) * 4 + 1 AS INT), cast((eid % 2) * 30 AS INT), 0) AS event_ts
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.edge_events;

-- E4 schema diff: column renamed (country -> country_name) + DECIMAL -> DOUBLE ---
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.edge_geo AS
SELECT
  geo_id,
  country AS country_name,
  cast(lat AS DOUBLE) AS lat
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.edge_geo;

-- E11 trailing whitespace ; E12 unicode NFC -> NFD (decomposed é) ---------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.edge_string AS
SELECT
  sid,
  concat(name_ws, '   ') AS name_ws,
  concat('caf', 'e', decode(unhex('CC81'), 'UTF-8')) AS name_unicode   -- 'e' + combining acute
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.edge_string;

-- E6 target NULL where source populated (genuine data / route to data owner) ----
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.dim_supplier AS
SELECT
  supplier_id,
  supplier_name,
  CASE WHEN supplier_id % 10 = 0 THEN NULL ELSE contact_email END AS contact_email
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_supplier;

-- E7 semi-structured genuine value difference (retries 3 -> 5) ------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.dim_config AS
SELECT
  config_id,
  CASE WHEN config_id % 4 = 0 THEN '{"retries":5,"mode":"auto"}' ELSE settings_json END AS settings_json
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_config;

-- E8 NULL -> sentinel -1 --------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.fact_inventory AS
SELECT
  item_id,
  coalesce(reorder_level, -1) AS reorder_level
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_inventory;

-- E9 1/0 -> 'true'/'false' ------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.dim_flag AS
SELECT
  flag_id,
  CASE WHEN active_flag = 1 THEN 'true' ELSE 'false' END AS active_flag
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_flag;

-- E10 non-idempotent merge -> duplicate payment rows (extra in target) ----------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.fact_payments AS
SELECT payment_id, amount FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_payments
UNION ALL
SELECT payment_id, amount FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_payments
WHERE payment_id <= 10;

-- E5 week-start config: Sunday-start instead of source Monday-start -------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.agg_weekly_sales AS
SELECT
  store_id,
  week_id,
  date_sub(week_start, 1) AS week_start,   -- Sunday = Monday - 1 day
  revenue
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.agg_weekly_sales;
