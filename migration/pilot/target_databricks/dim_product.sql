-- PILOT TARGET (Databricks) — mig_target.dim_product   [migrated from RETAIL.SOURCE.DIM_PRODUCT]
-- DEFECT S4 (string_format): SKU lower-cased with trailing whitespace during the transform.
-- UNIT_PRICE correctly kept at DECIMAL(18,4).

CREATE TABLE IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_target.dim_product (
  product_id   BIGINT NOT NULL COMMENT 'Product surrogate key',
  sku          STRING          COMMENT 'Stock keeping unit',
  product_name STRING          COMMENT 'Product display name',
  category     STRING          COMMENT 'Product category',
  unit_price   DECIMAL(18,4)   COMMENT 'Unit price',
  CONSTRAINT pk_dim_product PRIMARY KEY (product_id) RELY
) CLUSTER BY (product_id)
COMMENT 'Product dimension (migrated)';

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.dim_product
SELECT
  CAST(product_id AS BIGINT)     AS product_id,
  concat(lower(sku), '  ')       AS sku,          -- S4: lower + trailing whitespace
  product_name,
  category,
  CAST(unit_price AS DECIMAL(18,4)) AS unit_price
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_product;
