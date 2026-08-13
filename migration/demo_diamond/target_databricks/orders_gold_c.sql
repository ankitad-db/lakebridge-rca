-- DEMO DIAMOND · TARGET (Databricks) — mig_demo_diamond.orders_gold_c   [LEAF E, arm C]
-- Migrated derivation for the arm-C leaf, with the diamond's transforms INLINED so the
-- code-aware RCA (sqlglot) can correlate each defect to the exact expression that caused it:
--
--   order_ts : DEFECT (timezone)      — + 5:30 with no UTC normalization  [enriched, shared]
--   amount   : DEFECT (type_precision)— cast to DECIMAL(18,2), loses 4dp  [enriched, shared]
--   sku      : DEFECT (string_format) — lower() + trailing space          [curated_c, arm C]
--   customer_id / status / region : clean passthrough (no finding expected).

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_gold_c
SELECT
  CAST(order_id AS BIGINT)                        AS order_id,
  CAST(customer_id AS BIGINT)                     AS customer_id,
  order_ts + make_interval(0, 0, 0, 0, 5, 30, 0)  AS order_ts,    -- timezone defect (+5:30, no UTC norm)
  CAST(amount AS DECIMAL(18,2))                   AS amount,       -- scale-loss defect (NUMBER(18,4) -> (18,2))
  concat(lower(sku), ' ')                         AS sku,          -- string_format defect (lower + trailing space)
  status,
  region
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_raw;
