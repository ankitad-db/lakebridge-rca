-- Demo DEEP-DIAMOND test bed — the "whole feature set on one topology" scenario.
--
-- A Snowflake -> Databricks migration modelled as a 4-deep DIAMOND so a single bed
-- exercises every RCA capability at once: two RCA tiers, deep column-level lineage
-- trace-back, sibling isolation, a distractor, blast radius and clustering.
--
--   raw_a  (clean root)                                              L3
--     |
--   shared_b   ⚠ amount   cast DECIMAL(18,4)->(18,2)   [type_precision -> TIER 1 deterministic]
--     |        ⚠ net_amount round(gross*1.08,2)         [business drift  -> TIER 2 LLM fallback]
--    / \        (both defects share ONE upstream root: shared_b)      L2
--   /   \
-- branch_c  branch_d   ⚠ sku concat(lower(sku),'  ')   [string_format DISTRACTOR — D arm ONLY]  L1
--   |         |
-- leaf_e    leaf_f     (E<-C has NO sku; F<-D has sku)                 L0  ← the reconciled LEAVES
--   |         |
-- report_e  report_f   (downstream consumers -> give the leaves a real BLAST RADIUS)
--
-- Reconcile pairs (join a_id):
--   leaf_e_src  vs  leaf_e_tgt     -> amount (precision) + net_amount (business drift). NO sku.
--   leaf_f_src  vs  leaf_f_tgt     -> amount + net_amount + sku (string_format).
--
-- What this bed proves in ONE run:
--   * TIER 1 deterministic : amount 18,4->18,2 scale loss (numeric probe) and sku lower()+space
--                            (string probe) — probe-fingerprinted, drill-down-confirmed, no LLM.
--   * TIER 2 LLM fallback   : net_amount recomputed as gross*1.08 (8% tax) instead of the source
--                            rule gross*0.90 (10% discount). No probe fingerprints it -> stays
--                            needs-review -> Claude proposes hypothesis + confirming query.
--   * DEEP lineage trace    : both defects surface on the leaf but entered at shared_b, 3 hops up;
--                            the depth-agnostic walk reaches root raw_a.
--   * SIBLING ISOLATION     : RCA on leaf_e (amount/net_amount only) must NOT surface D's sku
--                            distractor — column-scoped lineage keeps the sibling arm out.
--   * BLAST RADIUS          : leaf_e/leaf_f each feed a report_* consumer, so the fix is
--                            prioritized by real downstream propagation.
--   * CLUSTERING            : amount (both leaves) and net_amount (both leaves) each collapse to
--                            one shared upstream root at shared_b — 2 root causes, not 4 tickets.
--   * CLEAN controls        : gross_amount and qty match everywhere.
--
-- Catalog: fevm_ps_dr_us_east_2_catalog   Schema: mig_demo_diamond_deep
-- Every table is CTAS so Unity Catalog captures column/table lineage. The source LEAVES are
-- seeded INDEPENDENTLY from range() with the CORRECT business values, so the recon source is
-- not part of the target pipeline lineage — the target lineage root is raw_a_tgt, exactly like
-- a real migrated pipeline. UC lineage populates a few minutes after these runs.

CREATE SCHEMA IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep;

-- ════════════════════════════════════════════════════════════════════════════
-- SOURCE OF TRUTH (the "Snowflake" side of the recon) — CORRECT values.
--   amount     : full precision DECIMAL(18,4)
--   net_amount : round(gross_amount * 0.90, 2)   (10% loyalty discount — the real rule)
--   sku        : original case 'SKU-<id>'
-- Seeded independently for each reconciled leaf.
-- ════════════════════════════════════════════════════════════════════════════

-- leaf_e source — arm C shape: amount, gross, net_amount, qty   (NO sku)
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.leaf_e_src AS
SELECT
  cast(id AS BIGINT)                                              AS a_id,
  cast(id * 1.2345 + 0.6789 AS DECIMAL(18,4))                     AS amount,
  cast(50 + (id % 400) * 1.37 AS DECIMAL(18,4))                   AS gross_amount,
  cast(round((50 + (id % 400) * 1.37) * 0.90, 2) AS DECIMAL(18,4)) AS net_amount,
  cast(id % 7 AS INT)                                             AS qty
FROM range(1, 501) AS t(id);

-- leaf_f source — arm D shape: amount, gross, net_amount, sku, qty
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.leaf_f_src AS
SELECT
  cast(id AS BIGINT)                                              AS a_id,
  cast(id * 1.2345 + 0.6789 AS DECIMAL(18,4))                     AS amount,
  cast(50 + (id % 400) * 1.37 AS DECIMAL(18,4))                   AS gross_amount,
  cast(round((50 + (id % 400) * 1.37) * 0.90, 2) AS DECIMAL(18,4)) AS net_amount,
  concat('SKU-', cast(id AS STRING))                              AS sku,
  cast(id % 7 AS INT)                                             AS qty
FROM range(1, 501) AS t(id);

-- ════════════════════════════════════════════════════════════════════════════
-- TARGET PIPELINE (Databricks) — the DIAMOND with lineage + defects.
-- ════════════════════════════════════════════════════════════════════════════

-- L3 · raw_a — clean root of the lineage. Correct values, carries sku for the D arm.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.raw_a_tgt AS
SELECT
  cast(id AS BIGINT)                                              AS a_id,
  cast(id * 1.2345 + 0.6789 AS DECIMAL(18,4))                     AS amount,
  cast(50 + (id % 400) * 1.37 AS DECIMAL(18,4))                   AS gross_amount,
  cast(round((50 + (id % 400) * 1.37) * 0.90, 2) AS DECIMAL(18,4)) AS net_amount,
  concat('SKU-', cast(id AS STRING))                              AS sku,
  cast(id % 7 AS INT)                                             AS qty
FROM range(1, 501) AS t(id);

-- L2 · shared_b — THE SHARED DEFECT NODE. Two defects injected here:
--   amount     : cast to DECIMAL(18,2)          -> scale loss  [type_precision -> Tier 1]
--   net_amount : recomputed as round(gross*1.08) -> 8% tax     [business drift -> Tier 2 LLM]
-- gross_amount / sku / qty are clean passthrough.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.shared_b_tgt AS
SELECT
  a_id,
  cast(amount AS DECIMAL(18,2))                    AS amount,       -- ⚠ scale loss (18,4)->(18,2)
  gross_amount,
  cast(round(gross_amount * 1.08, 2) AS DECIMAL(18,4)) AS net_amount, -- ⚠ 8% tax, not the 10% discount
  sku,
  qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.raw_a_tgt;

-- L1 · branch_c — clean passthrough of shared_b, drops sku (arm C has no sku).
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.branch_c_tgt AS
SELECT a_id, amount, gross_amount, net_amount, qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.shared_b_tgt;

-- L1 · branch_d — DISTRACTOR arm: sku lower-cased + trailing whitespace. amount/net passthrough.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.branch_d_tgt AS
SELECT
  a_id, amount, gross_amount, net_amount,
  concat(lower(sku), '  ')                         AS sku,          -- ⚠ string_format (D arm only)
  qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.shared_b_tgt;

-- L0 · leaf_e — reconciled LEAF from branch_c (inherits amount+net defects; NO sku).
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.leaf_e_tgt AS
SELECT a_id, amount, gross_amount, net_amount, qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.branch_c_tgt;

-- L0 · leaf_f — reconciled LEAF from branch_d (inherits amount+net defects AND sku distractor).
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.leaf_f_tgt AS
SELECT a_id, amount, gross_amount, net_amount, sku, qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.branch_d_tgt;

-- Downstream consumers — give the reconciled leaves a real BLAST RADIUS.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.report_e_tgt AS
SELECT a_id, amount, net_amount, qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.leaf_e_tgt;

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.report_f_tgt AS
SELECT a_id, amount, net_amount, sku, qty
FROM fevm_ps_dr_us_east_2_catalog.mig_demo_diamond_deep.leaf_f_tgt;
