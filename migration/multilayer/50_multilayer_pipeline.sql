-- Multi-layer lineage test bed.
--
-- Models a medallion pipeline where a DEFECT is injected in an INTERMEDIATE layer
-- (sales_stg) and then passed through UNCHANGED to the reconciled target (sales_gold),
-- while the source-of-truth (sales_src) holds the correct values. Reconciling
-- sales_src vs sales_gold surfaces the mismatch on the TARGET, but the root cause is
-- TWO hops upstream (sales_stg) — the target's *immediate* parent (sales_curated) is a
-- clean passthrough. This forces the RCA trace-back to walk PAST the first hop:
--
--     sales_gold  <-  sales_curated  <-  sales_stg (BUG)  <-  sales_raw (root)
--        (0)              (1, clean)         (2, defect)          (3, root)
--
-- Every table is built with CTAS so Unity Catalog captures column/table lineage
-- (system.access.column_lineage / table_lineage). With `use_uc_lineage: true` the RCA
-- attaches a "Lineage trace-back (3 hops to root `sales_raw`)" line, pointing the
-- investigation at the intermediate layer instead of the reconciled target.
--
-- Catalog: fevm_ps_dr_us_east_2_catalog   Schema: mig_multilayer
-- Run this once; UC lineage can take a few minutes to populate after the CTAS runs.

CREATE SCHEMA IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_multilayer;

-- Source-of-truth (the "source system" side of the recon) — correct high-precision amount.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_multilayer.sales_src AS
SELECT
  id                                        AS sale_id,
  cast(id * 1.25 + 0.37 AS DECIMAL(18,4))   AS amount,       -- fractional, never whole
  cast((id % 7) + 1 AS INT)                 AS qty
FROM range(1, 201) AS t(id);

-- L1 · raw — root of the TARGET pipeline; same correct values, landed in the lake.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_multilayer.sales_raw AS
SELECT
  id                                        AS sale_id,
  cast(id * 1.25 + 0.37 AS DECIMAL(18,4))   AS amount,
  cast((id % 7) + 1 AS INT)                 AS qty
FROM range(1, 201) AS t(id);

-- L2 · staging — THE BUG. `amount` is rounded to whole units (scale loss / rounding-mode
-- difference); `qty` is untouched. This is where the difference actually enters.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_multilayer.sales_stg AS
SELECT
  sale_id,
  cast(round(amount, 0) AS DECIMAL(18,4))   AS amount,       -- defect injected in L2
  qty
FROM fevm_ps_dr_us_east_2_catalog.mig_multilayer.sales_raw;

-- L3 · curated — clean passthrough. The bug is now invisible one hop above the target.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_multilayer.sales_curated AS
SELECT sale_id, amount, qty
FROM fevm_ps_dr_us_east_2_catalog.mig_multilayer.sales_stg;

-- L4 · gold — the reconciled TARGET; clean passthrough of curated.
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_multilayer.sales_gold AS
SELECT sale_id, amount, qty
FROM fevm_ps_dr_us_east_2_catalog.mig_multilayer.sales_curated;
