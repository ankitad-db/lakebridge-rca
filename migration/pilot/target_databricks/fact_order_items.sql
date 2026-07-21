-- PILOT TARGET (Databricks) — mig_target.fact_order_items   [migrated from RETAIL.SOURCE.FACT_ORDER_ITEMS]
-- DEFECT S1 (type_precision): AMOUNT migrated as DECIMAL(18,2) instead of source DECIMAL(18,4) -> scale loss.
-- DEFECT S7 (volume_extra): a non-idempotent re-load fans out duplicate rows for order_id <= 5.

CREATE TABLE IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_target.fact_order_items (
  order_item_id BIGINT NOT NULL COMMENT 'Order item id',
  order_id      BIGINT          COMMENT 'FK to fact_orders',
  product_id    BIGINT          COMMENT 'FK to dim_product',
  qty           INT             COMMENT 'Quantity',
  amount        DECIMAL(18,2)   COMMENT 'Line amount (NOTE: reduced scale vs source DECIMAL(18,4))',
  discount      DECIMAL(18,4)   COMMENT 'Line discount',
  CONSTRAINT pk_fact_order_items PRIMARY KEY (order_item_id) RELY
) CLUSTER BY (order_item_id)
COMMENT 'Order items fact (migrated)';

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.fact_order_items
SELECT CAST(order_item_id AS BIGINT) AS order_item_id, order_id, product_id, qty,
       CAST(amount AS DECIMAL(18,2)) AS amount,          -- S1: scale 4 -> 2
       CAST(discount AS DECIMAL(18,4)) AS discount
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_order_items
UNION ALL
SELECT CAST(order_item_id + 1000000 AS BIGINT) AS order_item_id, order_id, product_id, qty,
       CAST(amount AS DECIMAL(18,2)) AS amount, CAST(discount AS DECIMAL(18,4)) AS discount
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.fact_order_items
WHERE order_id <= 5;                                      -- S7: duplicate fan-out
