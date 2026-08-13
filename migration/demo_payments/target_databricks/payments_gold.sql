-- DEMO PAYMENTS · TARGET (Databricks) — mig_demo_payments.payments_gold   [reconciled LEAF]
-- Migrated derivation for the leaf, with the pipeline's transforms INLINED so the code-aware
-- RCA (sqlglot) and the LLM fallback can correlate each mismatch to the exact expression:
--
--   payment_ts : DEFECT (timezone)      — + 5:30 with no UTC normalization   [enriched]
--   net_amount : DEFECT (business drift)— round(gross_amount * 1.08, 2)       [enriched]
--                The source rule was round(GROSS_AMOUNT * 0.90, 2) (10% discount); the
--                migration applied an 8% TAX instead. Not a rounding/scale/precision issue
--                and not a clean 10x/100x factor -> no deterministic probe fingerprints it,
--                so it is handed to the LLM fallback, which confirms it with a query.
--   gross_amount / customer_id / currency / status : clean passthrough (no finding expected).

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_demo_payments.payments_gold
SELECT
  CAST(payment_id AS BIGINT)                        AS payment_id,
  CAST(customer_id AS BIGINT)                       AS customer_id,
  payment_ts + make_interval(0, 0, 0, 0, 5, 30, 0)  AS payment_ts,    -- timezone defect (+5:30, no UTC norm)
  CAST(gross_amount AS DECIMAL(18,4))               AS gross_amount,
  CAST(round(gross_amount * 1.08, 2) AS DECIMAL(18,4)) AS net_amount,  -- business drift: +8% tax, not the -10% discount
  currency,
  status
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_payments.payments_raw;
