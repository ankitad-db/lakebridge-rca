-- =====================================================================================
-- HYBRID demo TARGET — Retail "Sales & Revenue" mart (mig_rev_hyb_tgt)
-- Migrated from the same Snowflake EDW source (mig_rev_src) as the deterministic bed, but
-- carries a defect the deterministic Tier-1 rules CANNOT classify — so the agentic Tier-2
-- (Foundation Model) proposes the cause + a confirming query, and the engine promotes it
-- ONLY if the query confirms. Shows "deterministic for the easy 90%, agentic for the hard 10%".
--
--   AGENTIC  net_revenue  discount & tax applied ADDITIVELY instead of multiplicatively.
--            Source: qty*price*(1-discount)*(1+tax) = qty*price*(1 - d + t - d*t).
--            Target keeps every term EXCEPT the -d*t cross-term, so revenue is over-stated by
--            qty*price*discount*tax. A real formula-precedence migration bug; no Tier-1 rule
--            matches it -> the FM reconstructs the column from source inputs + a query confirms.
--   DETERMINISTIC  unit_price  ROUND(...,2)/DECIMAL(18,2) -> precision / scale loss (Tier-1).
--
-- Everything else matches source exactly.
-- =====================================================================================

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_rev_hyb_tgt.fact_sales AS
SELECT
    r.order_id,
    r.order_ts                                                                      AS order_ts_utc,
    r.customer_id,
    r.product_id,
    r.store_id,
    r.quantity,
    CAST(ROUND(r.unit_price, 2) AS DECIMAL(18,2))                                    AS unit_price,
    r.discount_pct,
    r.tax_rate,
    r.currency,
    r.status_code,
    initcap(trim(r.customer_name_raw))                                              AS customer_name,
    (r.is_active_raw = 'Y')                                                          AS is_active,
    ROUND( r.quantity * r.unit_price * (1 + r.tax_rate)
         - r.quantity * r.unit_price * r.discount_pct , 4)                          AS net_revenue,
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
