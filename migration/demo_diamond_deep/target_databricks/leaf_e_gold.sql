-- DEEP-DIAMOND · TARGET (Databricks) — mig_demo_diamond_deep.leaf_e_tgt   [reconciled LEAF, arm C]
-- The diamond's arm-C transforms (raw_a -> shared_b -> branch_c -> leaf_e) INLINED so the
-- code-aware RCA (sqlglot) and the LLM fallback correlate each mismatch to the exact expression:
--
--   amount     : DEFECT (type_precision)  — cast(amount AS DECIMAL(18,2)) loses (18,4)->(18,2)  [shared_b]
--   net_amount : DEFECT (business drift)  — round(gross_amount * 1.08, 2)                        [shared_b]
--                The source rule was round(GROSS_AMOUNT * 0.90, 2) (10% discount); the migration
--                applied an 8% TAX instead. Not a rounding/scale/precision issue and not a clean
--                10x/100x factor -> no deterministic probe fingerprints it, so it is handed to the
--                LLM fallback, which confirms it with a query.
--   gross_amount / qty : clean passthrough (no finding expected).
-- Arm C has NO sku column — the D-arm sku distractor must never appear in leaf_e's RCA.

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.leaf_e_tgt
SELECT
  CAST(a_id AS BIGINT)                                  AS a_id,
  CAST(amount AS DECIMAL(18,2))                         AS amount,       -- type_precision defect (18,4->18,2)
  CAST(gross_amount AS DECIMAL(18,4))                   AS gross_amount,
  CAST(round(gross_amount * 1.08, 2) AS DECIMAL(18,4))  AS net_amount,   -- business drift: +8% tax, not -10% discount
  CAST(qty AS INT)                                      AS qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.raw_a_tgt;
