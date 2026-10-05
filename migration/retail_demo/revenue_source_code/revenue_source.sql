-- =====================================================================================
-- SOURCE EDW logic — Retail "Sales & Revenue" mart (mig_rev_src.*), the ground truth.
-- Parsed by the RCA (source_transpiled) to recover each column's SOURCE derivation, so a
-- finding can show the source logic side-by-side with the migrated target logic.
-- Column aliases match the target build (revenue_target.sql) so they pair up per column.
-- =====================================================================================

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_rev_src.fact_sales AS
SELECT
    r.order_id,
    r.order_ts                                                                      AS order_ts_utc,   -- canonical (no shift)
    r.customer_id,
    r.product_id,
    r.store_id,
    r.quantity,
    r.unit_price                                                                    AS unit_price,     -- DECIMAL(18,4), full scale
    r.discount_pct,
    r.tax_rate,
    r.currency,
    r.status_code,
    initcap(trim(r.customer_name_raw))                                              AS customer_name,  -- proper case
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
      AND fx.fx_date  = r.order_dt;

-- ------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_rev_src.dim_customer AS
SELECT
    c.customer_id,
    initcap(trim(c.customer_name))                                                  AS customer_name,  -- proper case
    LOWER(c.email)                                                                  AS email,
    c.segment,
    c.country,
    (c.is_active_raw = 'Y')                                                         AS is_active
FROM fevm_ps_dr_us_east_2_catalog.mig_rev_src._raw_customer c;
