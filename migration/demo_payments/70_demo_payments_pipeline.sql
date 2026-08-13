-- Demo payments test bed — the "two tiers" scenario.
--
-- Models a Snowflake -> Databricks "payments" migration built to contrast the RCA's
-- TWO tiers in a single, realistic story:
--
--   payments_raw (root, correct)                 <- L2 root of the TARGET pipeline
--     |
--     v
--   payments_enriched   ⚠ TWO DEFECTS            <- L1
--     |     • payment_ts + 5:30, no UTC norm      -> TIER 1 deterministic (timezone probe)
--     |     • net_amount recomputed as gross*1.08 -> TIER 2 LLM fallback (no probe fingerprint)
--     v
--   payments_gold                                 <- L0 the reconciled LEAF
--
-- Reconcile source-of-truth `payments_src` against the leaf:
--   payments_src  vs  payments_gold   (join payment_id)
--
-- The business truth (source): net_amount = gross_amount * 0.90  (a 10% loyalty discount).
-- The migration regression (target): a developer rewrote the transform and applied an 8%
-- tax instead -> net_amount = round(gross_amount * 1.08, 2). Same DECIMAL scale, no rounding
-- pattern, no constant 10x/100x factor -> the deterministic numeric probe fires NOTHING, so
-- the finding stays `needs-review`. The LLM (Claude) fallback then reads the sampled values +
-- the migrated derivation, hypothesizes "target applies +8% instead of the -10% discount",
-- writes a CONFIRMING query, runs it, and only then promotes the verdict.
--
-- What this bed proves:
--   * TIER 1 deterministic : payment_ts is a constant +5:30 shift -> timezone / migration_induced.
--   * TIER 2 LLM fallback   : net_amount business-logic drift the probes can't name ->
--                             needs-review -> Claude proposes hypothesis + confirming query ->
--                             promoted to migration_induced (query-backed, not a guess).
--   * Depth-agnostic trace  : both defects surface on the leaf but were injected 1 hop up at
--                             payments_enriched; the walk reaches root payments_raw.
--   * Clean controls        : customer_id, gross_amount, currency, status match everywhere.
--
-- Catalog: fevm_ps_dr_us_east_2_catalog   Schema: mig_demo_payments
-- Every table is CTAS so Unity Catalog captures column/table lineage. `payments_src` and
-- `payments_raw` are seeded INDEPENDENTLY from range() with identical values, so the recon
-- source is NOT part of the target pipeline lineage — the lineage root is `payments_raw`,
-- exactly like a real migrated pipeline. UC lineage populates a few minutes after these runs.

CREATE SCHEMA IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_demo_payments;

-- ────────────────────────────────────────────────────────────────────────────
-- SOURCE OF TRUTH (the "Snowflake" side of the recon).
--   net_amount = gross * 0.90  (10% loyalty discount — the real business rule)
--   payment_ts = correct UTC instants
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_payments.payments_src AS
SELECT
  cast(id AS BIGINT)                                                      AS payment_id,
  cast((id % 100) + 1 AS BIGINT)                                          AS customer_id,
  timestamp('2024-03-01 00:00:00')
    + make_interval(0, 0, 0, 0, cast(id % 24 AS INT), 0, 0)               AS payment_ts,
  cast(50 + (id % 400) * 1.37 AS DECIMAL(18,4))                           AS gross_amount,
  cast(round((50 + (id % 400) * 1.37) * 0.90, 2) AS DECIMAL(18,4))        AS net_amount,
  element_at(array('USD','EUR','GBP','INR'), cast(id % 4 AS INT) + 1)     AS currency,
  element_at(array('CAPTURED','SETTLED','PENDING','REFUNDED'),
             cast(id % 4 AS INT) + 1)                                     AS status
FROM range(1, 501) AS t(id);

-- ────────────────────────────────────────────────────────────────────────────
-- TARGET PIPELINE — L2 · raw (root). Seeded independently, identical correct values.
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_payments.payments_raw AS
SELECT
  cast(id AS BIGINT)                                                      AS payment_id,
  cast((id % 100) + 1 AS BIGINT)                                          AS customer_id,
  timestamp('2024-03-01 00:00:00')
    + make_interval(0, 0, 0, 0, cast(id % 24 AS INT), 0, 0)               AS payment_ts,
  cast(50 + (id % 400) * 1.37 AS DECIMAL(18,4))                           AS gross_amount,
  cast(round((50 + (id % 400) * 1.37) * 0.90, 2) AS DECIMAL(18,4))        AS net_amount,
  element_at(array('USD','EUR','GBP','INR'), cast(id % 4 AS INT) + 1)     AS currency,
  element_at(array('CAPTURED','SETTLED','PENDING','REFUNDED'),
             cast(id % 4 AS INT) + 1)                                     AS status
FROM range(1, 501) AS t(id);

-- ────────────────────────────────────────────────────────────────────────────
-- L1 · enriched — THE DEFECT NODE. Two defects injected here:
--   payment_ts : + 5:30 with no UTC normalization           [timezone -> Tier 1 deterministic]
--   net_amount : recomputed as round(gross * 1.08, 2)        [business drift -> Tier 2 LLM]
-- customer_id / gross_amount / currency / status untouched.
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_payments.payments_enriched AS
SELECT
  payment_id,
  customer_id,
  payment_ts + make_interval(0, 0, 0, 0, 5, 30, 0)          AS payment_ts,   -- ⚠ timezone (+5:30)
  gross_amount,
  cast(round(gross_amount * 1.08, 2) AS DECIMAL(18,4))       AS net_amount,   -- ⚠ 8% tax, not the 10% discount
  currency,
  status
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_payments.payments_raw;

-- ────────────────────────────────────────────────────────────────────────────
-- L0 · gold — the reconciled LEAF. Clean passthrough of enriched.
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_payments.payments_gold AS
SELECT payment_id, customer_id, payment_ts, gross_amount, net_amount, currency, status
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_payments.payments_enriched;
