-- =====================================================================================
-- As-built Databricks TARGET ETL — Retail "Sales & Revenue" mart  (HYBRID demo bed)
-- Migrated from the Snowflake EDW to Unity Catalog. Reads the landed raw extract
-- (mig_hyb_src._raw / _raw_customer / _raw_product) and rebuilds the gold star schema.
--
-- This file is the single source of truth: it BUILDS mig_hyb_tgt.* and is also the
-- artifact the RCA skill parses (transpiled_output_dir) to surface the "Transformation
-- logic" behind each column and to seed the agentic Tier-2 hypotheses.
--
-- It carries the (intentional) migration defects the demo roots:
--   DETERMINISTIC (Tier-1 rules + a confirming query):
--     * unit_price   ROUND(...,2)          -> precision / scale loss
--     * customer_name UPPER(TRIM(...))      -> string-format (case)
--     * order_ts_utc  + INTERVAL 5 HOURS    -> timezone shift
--     * WHERE order_id % 500 <> 0           -> volume (dropped rows)
--   AGENTIC (Tier-1 leaves needs-review; the FM proposes a cause + confirming query):
--     * net_revenue  discount & tax applied ADDITIVELY -> the (1-d)(1+t) cross-term
--                    (+d*t) is missing: a real formula-precedence migration bug
--     * amount_usd   FX joined at MONTH-START grain instead of the daily rate
--     * status_bucket the 'R' (Returned) CASE branch was dropped -> falls to 'Unknown'
-- =====================================================================================

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_hyb_tgt.fact_sales AS
SELECT
    r.order_id,
    -- migration normalised timestamps to UTC by adding a fixed +5h (source was already local-canonical)
    r.order_ts + INTERVAL 5 HOURS                                                   AS order_ts_utc,
    r.customer_id,
    r.product_id,
    r.store_id,
    r.quantity,
    -- amounts landed as DECIMAL(18,2) on the target (scale loss vs the source DECIMAL(18,4))
    ROUND(r.unit_price, 2)                                                          AS unit_price,
    r.discount_pct,
    r.tax_rate,
    r.currency,
    r.status_code,
    -- names upper-cased on load (source kept proper case)
    UPPER(TRIM(r.customer_name_raw))                                                AS customer_name,
    (r.is_active_raw = 'Y')                                                         AS is_active,
    -- REVENUE: discount and tax were re-implemented ADDITIVELY. The source applies them
    -- multiplicatively as qty*price*(1-discount)*(1+tax); expanding that is
    -- qty*price*(1 - discount + tax - discount*tax). This target keeps every term EXCEPT
    -- the -discount*tax cross-term, so it over-states revenue by qty*price*discount*tax.
    ROUND( r.quantity * r.unit_price * (1 + r.tax_rate)
         - r.quantity * r.unit_price * r.discount_pct , 4)                          AS net_revenue,
    -- USD conversion: the FX lookup was migrated to join on the MONTH-START date
    -- (trunc month) rather than the order's daily rate, so intra-month drift is lost.
    ROUND(r.quantity * r.unit_price * fx.rate_to_usd, 2)                            AS amount_usd,
    -- status bucketing: the migrated CASE lost the 'R' (Returned) arm -> ELSE 'Unknown'
    CASE r.status_code
         WHEN 'A' THEN 'Active'
         WHEN 'C' THEN 'Closed'
         WHEN 'P' THEN 'Pending'
         ELSE 'Unknown'
    END                                                                             AS status_bucket
FROM fevm_ps_dr_us_east_2_catalog.mig_hyb_src._raw r
LEFT JOIN fevm_ps_dr_us_east_2_catalog.mig_hyb_src.dim_fx fx
       ON fx.currency = r.currency
      AND fx.fx_date  = trunc(r.order_dt, 'MM')
WHERE r.order_id % 500 <> 0;

-- ------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_hyb_tgt.dim_customer AS
SELECT
    c.customer_id,
    UPPER(TRIM(c.customer_name))                                                    AS customer_name,   -- string-format (case)
    LOWER(c.email)                                                                  AS email,
    c.segment,
    c.country,
    (c.is_active_raw = 'Y')                                                         AS is_active,
    -- loyalty tier re-derived; source thresholds were > / >=, target used only >= (edge shift)
    CASE WHEN c.lifetime_spend >= 10000 THEN 'PLATINUM'
         WHEN c.lifetime_spend >= 1000  THEN 'GOLD'
         ELSE 'STANDARD' END                                                        AS loyalty_tier
FROM fevm_ps_dr_us_east_2_catalog.mig_hyb_src._raw_customer c;

-- ------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_hyb_tgt.dim_product AS
SELECT
    p.product_id,
    UPPER(TRIM(p.product_name))                                                     AS product_name,    -- string-format (case)
    p.category,
    p.subcategory,
    ROUND(p.list_price, 2)                                                          AS list_price,       -- precision / scale loss
    concat_ws(' > ', p.category, p.subcategory)                                     AS category_path,    -- composite derived key
    to_json(named_struct(
        'sku',  concat('SKU-', CAST(p.product_id AS STRING)),
        'tier', CASE WHEN p.list_price > 100 THEN 'A' ELSE 'B' END,
        'hue',  p.product_id % 7))                                                  AS attrs             -- semi-structured
FROM fevm_ps_dr_us_east_2_catalog.mig_hyb_src._raw_product p;
