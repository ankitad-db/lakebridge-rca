-- Edge-case SOURCE tables for comprehensive RCA coverage.
-- Created in the same schema as the core scenario (mig_source_sim) so a single
-- Lakebridge recon run covers everything. Each table backs one or more scenarios
-- in migration/scenarios.yaml (E1..E12). Run before 41_edge_target.sql.
--
-- Catalog: fevm_ps_dr_us_east_2_catalog   Schema: mig_source_sim

-- E1 float-precision + E2 integer-overflow ------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.edge_numeric AS
SELECT
  id AS rid,
  cast(id * 0.111111 AS DECIMAL(18,6)) AS v_double,   -- high-scale decimal
  cast(3000000000 + id AS BIGINT)      AS big_id       -- > INT_MAX (overflows a 32-bit INT)
FROM range(1, 51) AS t(id);

-- E3 non-constant timezone offset ---------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.edge_events AS
SELECT
  id AS eid,
  cast(date_sub(current_date(), cast(id % 30 AS INT)) AS TIMESTAMP) AS event_ts
FROM range(1, 51) AS t(id);

-- E4 schema difference (rename + type + nullability) --------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.edge_geo AS
SELECT
  id AS geo_id,
  element_at(array('US','UK','DE','IN','FR'), cast((id % 5) + 1 AS INT)) AS country,
  cast(round(10 + id * 0.5, 6) AS DECIMAL(9,6)) AS lat
FROM range(1, 21) AS t(id);

-- E11 trailing whitespace + E12 unicode NFC/NFD -------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.edge_string AS
SELECT
  id AS sid,
  concat('Name', cast(id AS STRING)) AS name_ws,
  'café' AS name_unicode                 -- precomposed é (NFC, U+00E9)
FROM range(1, 21) AS t(id);

-- E6 target-NULL genuine-data (source populated) ------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_supplier AS
SELECT
  id AS supplier_id,
  concat('Supplier_', cast(id AS STRING)) AS supplier_name,
  concat('s', cast(id AS STRING), '@vendor.com') AS contact_email
FROM range(1, 51) AS t(id);

-- E7 semi-structured real value difference ------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_config AS
SELECT
  id AS config_id,
  '{"retries":3,"mode":"auto"}' AS settings_json
FROM range(1, 21) AS t(id);

-- E8 NULL vs sentinel ---------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_inventory AS
SELECT
  id AS item_id,
  CASE WHEN id % 4 = 0 THEN CAST(NULL AS INT) ELSE cast((id % 50) + 10 AS INT) END AS reorder_level
FROM range(1, 51) AS t(id);

-- E9 1/0 -> boolean -----------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_flag AS
SELECT
  id AS flag_id,
  cast(CASE WHEN id % 3 = 0 THEN 0 ELSE 1 END AS INT) AS active_flag
FROM range(1, 51) AS t(id);

-- E10 non-idempotent merge duplicates -----------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_payments AS
SELECT
  id AS payment_id,
  cast(round((id % 100) * 3.5, 2) AS DECIMAL(18,2)) AS amount
FROM range(1, 51) AS t(id);

-- E5 week-start / env-config (weekly aggregate; Spark date_trunc = Monday) -----
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_source_sim.agg_weekly_sales AS
SELECT
  store_id,
  weekofyear(d) AS week_id,
  cast(date_trunc('week', d) AS DATE) AS week_start,      -- Monday-start (source truth)
  cast(sum(amt) AS DECIMAL(18,2)) AS revenue
FROM (
  SELECT
    cast((id % 5) + 1 AS BIGINT) AS store_id,
    date_sub(current_date(), cast(id % 28 AS INT)) AS d,
    (id % 100) * 1.25 AS amt
  FROM range(1, 201) AS t(id)
)
GROUP BY store_id, weekofyear(d), cast(date_trunc('week', d) AS DATE);
