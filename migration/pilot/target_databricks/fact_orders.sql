-- PILOT TARGET (Databricks) — mig_target.fact_orders   [migrated from RETAIL.SOURCE.FACT_ORDERS]
-- DEFECT S2 (timezone): ORDER_TS shifted +5:30 with no UTC normalization (TIMESTAMP_LTZ story).
-- DEFECT S6 (volume_missing): load watermark drops order_id > 480 (late rows never land).

CREATE TABLE IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_target.fact_orders (
  order_id    BIGINT NOT NULL COMMENT 'Order id',
  customer_id BIGINT          COMMENT 'FK to dim_customer',
  store_id    BIGINT          COMMENT 'FK to dim_store',
  order_ts    TIMESTAMP       COMMENT 'Order timestamp',
  status      STRING          COMMENT 'Order status',
  order_total DECIMAL(18,4)   COMMENT 'Order total amount',
  CONSTRAINT pk_fact_orders PRIMARY KEY (order_id) RELY
) CLUSTER BY (order_id)
COMMENT 'Orders fact (migrated)';

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.fact_orders
SELECT
  CAST(order_id AS BIGINT)    AS order_id,
  CAST(customer_id AS BIGINT) AS customer_id,
  CAST(store_id AS BIGINT)    AS store_id,
  order_ts + make_interval(0, 0, 0, 0, 5, 30, 0) AS order_ts,   -- S2: +5:30, no UTC normalization
  status,
  CAST(order_total AS DECIMAL(18,4)) AS order_total
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_orders
WHERE order_id <= 480;                                          -- S6: watermark drops late rows
