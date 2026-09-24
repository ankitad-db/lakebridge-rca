CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_xl_tgt.fact_sales AS
SELECT r.order_id,
  r.order_ts + INTERVAL 5 HOURS AS order_ts_utc,
  r.customer_id, r.product_id, r.store_id, r.quantity,
  CAST(ROUND(r.unit_price, 2) AS DECIMAL(18,2)) AS unit_price,
  r.discount_pct, r.tax_rate, r.currency, r.status_code,
  UPPER(TRIM(r.customer_name_raw)) AS customer_name,
  (r.is_active_raw = 'Y') AS is_active,
  ROUND(r.quantity*r.unit_price*(1 + r.tax_rate) - r.quantity*r.unit_price*r.discount_pct, 4) AS net_revenue,
  ROUND(r.quantity*r.unit_price*fx.rate_to_usd, 2) AS amount_usd,
  CASE r.status_code WHEN 'A' THEN 'Active' WHEN 'C' THEN 'Closed' WHEN 'P' THEN 'Pending' ELSE 'Unknown' END AS status_bucket,
  uid, uid2, txn_hash, ext_id, note, lat, lon, score, m1, m2
FROM fevm_ps_dr_us_east_2_catalog.mig_xl_src._raw r
LEFT JOIN fevm_ps_dr_us_east_2_catalog.mig_xl_src.dim_fx fx ON fx.currency=r.currency AND fx.fx_date=trunc(r.order_dt,'MM')
WHERE r.order_id % 500 <> 0;
