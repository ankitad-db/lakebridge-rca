-- Demo diamond test bed — the flagship end-to-end scenario.
--
-- Models a Snowflake -> Databricks "orders" migration whose target pipeline is shaped
-- as a DIAMOND: one shared enrichment node fans out into two arms, then to two leaf
-- gold tables. Defects are injected at three different depths so a SINGLE bed exercises
-- the full RCA feature set:
--
--   orders_raw (root)                          <- L3 root of the TARGET pipeline (correct)
--     |
--     v
--   orders_enriched   ⚠ SHARED DEFECTS         <- L2  amount scale-loss + order_ts +5:30
--     |        \                                       (flows to BOTH arms -> clustering)
--     v         v
--   curated_c   curated_d                      <- L1
--   ⚠ sku       ⚠ volume                              arm C: sku lower()+trailing space
--   distractor  watermark                             arm D: drops order_id > 470
--     |           |
--     v           v
--   gold_c      gold_d                          <- L0 the two reconciled LEAVES (E / F)
--
-- Reconcile source-of-truth `orders_src` against each leaf:
--   orders_src  vs  orders_gold_c   (LEAF E)  -> flags amount, order_ts, sku
--   orders_src  vs  orders_gold_d   (LEAF F)  -> flags amount, order_ts, + missing rows
--
-- What this proves:
--   * Depth-agnostic trace-back : amount/order_ts surface on the leaf but the defect is
--     2 hops up at `orders_enriched`; sku is 1 hop up at `orders_curated_c`.
--   * Root-cause clustering     : amount+order_ts appear on BOTH leaves -> one shared root.
--   * Downstream blast-radius   : orders_enriched -> curated_c, curated_d, gold_c, gold_d.
--   * Distractor isolation      : sku only appears in the arm-C (gold_c) trace, never gold_d.
--   * Clean controls            : customer_id, status, region match everywhere (no finding).
--
-- Catalog: fevm_ps_dr_us_east_2_catalog   Schema: mig_demo_diamond
-- Every table is CTAS so Unity Catalog captures column/table lineage. `orders_src` and
-- `orders_raw` are seeded INDEPENDENTLY from range() with identical values, so the recon
-- source (orders_src) is NOT part of the target pipeline lineage — the lineage root is
-- `orders_raw`, exactly like a real migrated pipeline. UC lineage populates a few minutes
-- after these CTAS runs.

CREATE SCHEMA IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_demo_diamond;

-- ────────────────────────────────────────────────────────────────────────────
-- SOURCE OF TRUTH (the "Snowflake" side of the recon). Correct, high precision.
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_src AS
SELECT
  cast(id AS BIGINT)                                                   AS order_id,
  cast((id % 100) + 1 AS BIGINT)                                       AS customer_id,
  timestamp('2024-01-01 00:00:00')
    + make_interval(0, 0, 0, 0, cast(id % 24 AS INT), 0, 0)            AS order_ts,
  cast(20 + (id % 500) * 1.7777 AS DECIMAL(18,4))                      AS amount,
  concat('SKU-', lpad(cast(id % 50 AS STRING), 4, '0'))                AS sku,
  element_at(array('COMPLETED','SHIPPED','PENDING','RETURNED'),
             cast(id % 4 AS INT) + 1)                                  AS status,
  element_at(array('NA','EU','APAC','LATAM'), cast(id % 4 AS INT) + 1) AS region
FROM range(1, 501) AS t(id);

-- ────────────────────────────────────────────────────────────────────────────
-- TARGET PIPELINE — L3 · raw (root). Seeded independently, identical correct values.
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_raw AS
SELECT
  cast(id AS BIGINT)                                                   AS order_id,
  cast((id % 100) + 1 AS BIGINT)                                       AS customer_id,
  timestamp('2024-01-01 00:00:00')
    + make_interval(0, 0, 0, 0, cast(id % 24 AS INT), 0, 0)            AS order_ts,
  cast(20 + (id % 500) * 1.7777 AS DECIMAL(18,4))                      AS amount,
  concat('SKU-', lpad(cast(id % 50 AS STRING), 4, '0'))                AS sku,
  element_at(array('COMPLETED','SHIPPED','PENDING','RETURNED'),
             cast(id % 4 AS INT) + 1)                                  AS status,
  element_at(array('NA','EU','APAC','LATAM'), cast(id % 4 AS INT) + 1) AS region
FROM range(1, 501) AS t(id);

-- ────────────────────────────────────────────────────────────────────────────
-- L2 · enriched — THE SHARED DEFECT NODE. Two defects that fan out to BOTH arms:
--   amount  : cast to DECIMAL(18,2)  -> scale loss (4dp -> 2dp)      [type_precision]
--   order_ts: + 5:30 with no UTC normalization                       [timezone]
-- customer_id / sku / status / region are untouched here.
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_enriched AS
SELECT
  order_id,
  customer_id,
  order_ts + make_interval(0, 0, 0, 0, 5, 30, 0)   AS order_ts,   -- ⚠ timezone shift (shared)
  cast(amount AS DECIMAL(18,2))                     AS amount,     -- ⚠ scale loss (shared)
  sku,
  status,
  region
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_raw;

-- ────────────────────────────────────────────────────────────────────────────
-- ARM C · L1 curated_c — DISTRACTOR defect (arm C only):
--   sku : concat(lower(sku), ' ')  -> lowercase + trailing space    [string_format]
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_curated_c AS
SELECT
  order_id,
  customer_id,
  order_ts,
  amount,
  concat(lower(sku), ' ')   AS sku,   -- ⚠ string_format distractor (arm C only)
  status,
  region
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_enriched;

-- ARM C · L0 gold_c — reconciled LEAF E. Clean passthrough of curated_c.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_gold_c AS
SELECT order_id, customer_id, order_ts, amount, sku, status, region
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_curated_c;

-- ────────────────────────────────────────────────────────────────────────────
-- ARM D · L1 curated_d — VOLUME defect (arm D only):
--   load watermark drops order_id > 470  -> 30 rows never land       [volume_missing]
-- sku is left UNCHANGED here (clean) so sku is proven to be arm-C-only.
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_curated_d AS
SELECT order_id, customer_id, order_ts, amount, sku, status, region
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_enriched
WHERE order_id <= 470;   -- ⚠ volume_missing (arm D only): late rows never load

-- ARM D · L0 gold_d — reconciled LEAF F. Clean passthrough of curated_d.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_gold_d AS
SELECT order_id, customer_id, order_ts, amount, sku, status, region
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_curated_d;
