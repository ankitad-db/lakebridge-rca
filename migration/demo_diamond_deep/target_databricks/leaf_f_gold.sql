-- DEEP-DIAMOND · TARGET (Databricks) — mig_demo_diamond_deep.leaf_f_tgt   [reconciled LEAF, arm D]
-- The diamond's arm-D transforms (raw_a -> shared_b -> branch_d -> leaf_f) INLINED so the
-- code-aware RCA (sqlglot) and the LLM fallback correlate each mismatch to the exact expression:
--
--   amount     : DEFECT (type_precision)  — cast(amount AS DECIMAL(18,2)) loses (18,4)->(18,2)  [shared_b]
--   net_amount : DEFECT (business drift)  — round(gross_amount * 1.08, 2) instead of *0.90       [shared_b]
--   sku        : DEFECT (string_format)   — concat(lower(sku), '  ') lower-cases + pads          [branch_d]
--   gross_amount / qty : clean passthrough (no finding expected).

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.leaf_f_tgt
SELECT
  CAST(a_id AS BIGINT)                                  AS a_id,
  CAST(amount AS DECIMAL(18,2))                         AS amount,       -- type_precision defect (18,4->18,2)
  CAST(gross_amount AS DECIMAL(18,4))                   AS gross_amount,
  CAST(round(gross_amount * 1.08, 2) AS DECIMAL(18,4))  AS net_amount,   -- business drift: +8% tax, not -10% discount
  concat(lower(sku), '  ')                              AS sku,          -- string_format defect (lower + trailing spaces)
  CAST(qty AS INT)                                      AS qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.raw_a_tgt;
