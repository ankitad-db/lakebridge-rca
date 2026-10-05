-- =====================================================================================
-- As-built Databricks TARGET ETL — Retail "Sales & Revenue" mart  (REVENUE demo bed)
-- Migrated from the Snowflake EDW to Unity Catalog. Reads the landed raw extract
-- (mig_rev_src._raw / _raw_customer) and rebuilds the gold star schema.
--
-- This file is the source of truth: it BUILDS mig_rev_tgt.* and is the artifact the RCA
-- parses (transpiled_output_dir) to surface the "Transformation logic" behind each column.
-- The SELECT bodies are kept comment-free so the parsed transform expressions stay clean.
--
-- Every column is IDENTICAL to the source EDW logic EXCEPT the seeded, intentional migration
-- defects — so reconcile flags exactly these. All are cleanly diagnosed by the deterministic
-- Tier-1 rules and confirmed by a single query (no LLM):
--
--   HERO    fact_sales.order_ts_utc  = r.order_ts + INTERVAL 5 HOURS
--             The migration normalised timestamps to UTC by adding a fixed +5h, but the source
--             was already local-canonical. Every order is stamped 5 hours late, so evening
--             orders roll onto the next calendar day and daily-by-day revenue is wrong.
--             -> migration-induced, query-confirmed (constant 5h offset on every row).
--   SUPPORT fact_sales.unit_price = CAST(ROUND(unit_price,2) AS DECIMAL(18,2))
--             Amounts landed at scale 2 vs the source DECIMAL(18,4) -> precision / scale loss.
--   SUPPORT fact_sales.tax_rate = tax_rate + 0.0005 (declared +/-0.01 column threshold)
--             -> within tolerance / benign.
--   SUPPORT dim_customer.customer_name = UPPER(TRIM(customer_name))
--             Names upper-cased on load; the source kept proper case -> string-format (case).
--   SUPPORT fact_sales WHERE order_id % 500 <> 0
--             A stray load filter survived the migration and silently drops ~0.2% of orders,
--             so the target is missing rows the source has -> volume (rows matched ~99.8%).
--
-- amount_usd (daily FX), net_revenue, status_bucket, is_active etc. all match the source.
-- =====================================================================================

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_rev_tgt.fact_sales AS
SELECT
    r.order_id,
    r.order_ts + INTERVAL 5 HOURS                                                   AS order_ts_utc,
    r.customer_id,
    r.product_id,
    r.store_id,
    r.quantity,
    CAST(ROUND(r.unit_price, 2) AS DECIMAL(18,2))                                    AS unit_price,
    r.discount_pct,
    CAST(r.tax_rate + 0.0005 AS DECIMAL(9,4))                                        AS tax_rate,
    r.currency,
    r.status_code,
    initcap(trim(r.customer_name_raw))                                              AS customer_name,
    (r.is_active_raw = 'Y')                                                          AS is_active,
    ROUND(r.quantity * r.unit_price * (1 - r.discount_pct) * (1 + r.tax_rate), 4)    AS net_revenue,
    ROUND(r.quantity * r.unit_price * fx.rate_to_usd, 2)                             AS amount_usd,
    CASE r.status_code
         WHEN 'A' THEN 'Active'
         WHEN 'C' THEN 'Closed'
         WHEN 'P' THEN 'Pending'
         WHEN 'R' THEN 'Returned'
         ELSE 'Unknown'
    END                                                                             AS status_bucket
FROM fevm_ps_dr_us_east_2_catalog.mig_rev_src._raw r
LEFT JOIN fevm_ps_dr_us_east_2_catalog.mig_rev_src.dim_fx fx
       ON fx.currency = r.currency
      AND fx.fx_date  = r.order_dt
WHERE r.order_id % 500 <> 0;

-- ------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_rev_tgt.dim_customer AS
SELECT
    c.customer_id,
    UPPER(TRIM(c.customer_name))                                                    AS customer_name,
    LOWER(c.email)                                                                  AS email,
    c.segment,
    c.country,
    (c.is_active_raw = 'Y')                                                         AS is_active
FROM fevm_ps_dr_us_east_2_catalog.mig_rev_src._raw_customer c;
