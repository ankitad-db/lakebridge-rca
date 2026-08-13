-- DEMO DIAMOND · TARGET (Databricks) — mig_demo_diamond.orders_gold_d   [LEAF F, arm D]
-- Migrated derivation for the arm-D leaf, transforms INLINED for code-aware correlation:
--
--   order_ts : DEFECT (timezone)       — + 5:30 with no UTC normalization  [enriched, shared]
--   amount   : DEFECT (type_precision) — cast to DECIMAL(18,2), loses 4dp  [enriched, shared]
--   (rows)   : DEFECT (volume_missing) — load watermark drops order_id>470 [curated_d, arm D]
--   sku      : clean passthrough here (proves sku defect is arm-C-only).

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_gold_d
SELECT
  CAST(order_id AS BIGINT)                        AS order_id,
  CAST(customer_id AS BIGINT)                     AS customer_id,
  order_ts + make_interval(0, 0, 0, 0, 5, 30, 0)  AS order_ts,    -- timezone defect (+5:30, no UTC norm)
  CAST(amount AS DECIMAL(18,2))                   AS amount,       -- scale-loss defect (NUMBER(18,4) -> (18,2))
  sku,
  status,
  region
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond.orders_raw
WHERE order_id <= 470;                                            -- volume_missing: late rows never load
