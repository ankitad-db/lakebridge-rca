-- =====================================================================================
-- As-built Databricks TARGET ETL — Retail "Sales & Revenue" mart  (DETERMINISTIC bed)
-- Migrated from the Snowflake EDW to Unity Catalog. Same rich composed transforms as the
-- hybrid bed, but every seeded defect is CLEANLY categorizable by the deterministic Tier-1
-- rules and confirmed by a single query — no LLM needed. Builds mig_det_tgt.* and is the
-- artifact the skill parses for the "Transformation logic" highlight.
--
-- Seeded defects (all deterministic, each query-confirmed):
--   * unit_price   CAST(ROUND(...,2) AS DECIMAL(18,2))   -> type_precision + schema type diff
--   * net_revenue  correct formula, ROUND to scale 2      -> type_precision (scale loss)
--   * customer_name UPPER(TRIM(...))                       -> string_format (case)
--   * is_active    'Y'/'N' -> 'true'/'false' string        -> null_boolean mapping
--   * order_ts_utc + INTERVAL 5 HOURS                      -> timezone shift
--   * tax_rate     + 0.0005  (declared threshold +/-0.01)  -> within-tolerance / benign
--   * WHERE order_id % 500 <> 0                            -> volume_missing (dropped rows)
--   * UNION ALL duplicate of order_id % 997 = 0            -> volume_extra (fan-out)
--   * aggregates-reconcile SUM(net_revenue) by is_active   -> aggregate mismatch
-- =====================================================================================

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_det_tgt.fact_sales AS
SELECT * FROM (
    SELECT
        r.order_id,
        r.order_ts + INTERVAL 5 HOURS                                               AS order_ts_utc,     -- timezone
        r.customer_id,
        r.product_id,
        r.store_id,
        r.quantity,
        CAST(ROUND(r.unit_price, 2) AS DECIMAL(18,2))                               AS unit_price,        -- precision + schema type
        r.discount_pct,
        CAST(r.tax_rate + 0.0005 AS DECIMAL(9,4))                                   AS tax_rate,          -- within declared threshold (benign)
        r.currency,
        r.status_code,
        UPPER(TRIM(r.customer_name_raw))                                            AS customer_name,     -- string-format (case)
        CASE WHEN r.is_active_raw = 'Y' THEN 'true' ELSE 'false' END                AS is_active,         -- boolean mapping
        -- revenue uses the SAME correct multiplicative formula as the source, only the
        -- landed scale differs (DECIMAL .,2 vs the source's .,4) -> a clean scale loss.
        ROUND(r.quantity * r.unit_price * (1 - r.discount_pct) * (1 + r.tax_rate), 2) AS net_revenue,     -- precision (scale)
        ROUND(r.quantity * r.unit_price * fx.rate_to_usd, 2)                        AS amount_usd,        -- correct (daily FX)
        CASE r.status_code
             WHEN 'A' THEN 'Active' WHEN 'C' THEN 'Closed'
             WHEN 'P' THEN 'Pending' WHEN 'R' THEN 'Returned'
             ELSE 'Unknown' END                                                     AS status_bucket      -- correct (full CASE)
    FROM fevm_ps_dr_us_east_2_catalog.mig_det_src._raw r
    LEFT JOIN fevm_ps_dr_us_east_2_catalog.mig_det_src.dim_fx fx
           ON fx.currency = r.currency AND fx.fx_date = r.order_dt
    WHERE r.order_id % 500 <> 0                                                                            -- volume_missing

    UNION ALL
    -- a re-processed batch was loaded twice for one shard -> duplicate rows (volume_extra)
    SELECT
        r.order_id, r.order_ts + INTERVAL 5 HOURS, r.customer_id, r.product_id, r.store_id, r.quantity,
        CAST(ROUND(r.unit_price, 2) AS DECIMAL(18,2)), r.discount_pct, CAST(r.tax_rate + 0.0005 AS DECIMAL(9,4)),
        r.currency, r.status_code, UPPER(TRIM(r.customer_name_raw)),
        CASE WHEN r.is_active_raw = 'Y' THEN 'true' ELSE 'false' END,
        ROUND(r.quantity * r.unit_price * (1 - r.discount_pct) * (1 + r.tax_rate), 2),
        ROUND(r.quantity * r.unit_price * fx.rate_to_usd, 2),
        CASE r.status_code WHEN 'A' THEN 'Active' WHEN 'C' THEN 'Closed'
                           WHEN 'P' THEN 'Pending' WHEN 'R' THEN 'Returned' ELSE 'Unknown' END
    FROM fevm_ps_dr_us_east_2_catalog.mig_det_src._raw r
    LEFT JOIN fevm_ps_dr_us_east_2_catalog.mig_det_src.dim_fx fx
           ON fx.currency = r.currency AND fx.fx_date = r.order_dt
    WHERE r.order_id % 997 = 0 AND r.order_id % 500 <> 0
);

-- ------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_det_tgt.dim_product AS
SELECT
    p.product_id,
    UPPER(TRIM(p.product_name))                                                     AS product_name,    -- string-format (case)
    p.category,
    p.subcategory,
    CAST(ROUND(p.list_price, 2) AS DECIMAL(18,2))                                   AS list_price,       -- precision + schema type
    concat_ws(' > ', p.category, p.subcategory)                                     AS category_path,
    to_json(named_struct(
        'sku',  concat('SKU-', CAST(p.product_id AS STRING)),
        'tier', CASE WHEN p.list_price > 100 THEN 'A' ELSE 'B' END))                AS attrs
FROM fevm_ps_dr_us_east_2_catalog.mig_det_src._raw_product p;

-- ------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_det_tgt.dim_customer AS
SELECT
    c.customer_id,
    UPPER(TRIM(c.customer_name))                                                    AS customer_name,   -- string-format (case)
    LOWER(c.email)                                                                  AS email,
    c.segment,
    c.country,
    CASE WHEN c.is_active_raw = 'Y' THEN 'true' ELSE 'false' END                    AS is_active        -- boolean mapping
FROM fevm_ps_dr_us_east_2_catalog.mig_det_src._raw_customer c;
