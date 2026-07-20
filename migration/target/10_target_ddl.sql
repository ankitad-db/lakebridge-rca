-- Target (Databricks) DDL for the migrated retail warehouse.
-- Best practices: Unity Catalog namespace, managed Delta, explicit types with
-- comments, liquid clustering, and informational PRIMARY KEY constraints (RELY).
--
-- Type-mapping note: fact_order_items.amount is DECIMAL(18,2) here while the
-- source is DECIMAL(18,4) -- this is the intentional precision-loss defect (S1).
--
-- Catalog: fevm_ps_dr_us_east_2_catalog   Schema: mig_target

CREATE SCHEMA IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_target
  COMMENT 'Migrated Databricks target for the retail warehouse';

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.dim_store (
  store_id   BIGINT  NOT NULL COMMENT 'Store surrogate key',
  store_name STRING           COMMENT 'Store display name',
  region     STRING           COMMENT 'Sales region',
  store_tz   STRING           COMMENT 'Store timezone (IANA)',
  CONSTRAINT pk_dim_store PRIMARY KEY (store_id) RELY
) CLUSTER BY (store_id)
COMMENT 'Store dimension';

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.dim_product (
  product_id   BIGINT        NOT NULL COMMENT 'Product surrogate key',
  sku          STRING                 COMMENT 'Stock keeping unit',
  product_name STRING                 COMMENT 'Product display name',
  category     STRING                 COMMENT 'Product category',
  unit_price   DECIMAL(18,4)          COMMENT 'Unit price',
  CONSTRAINT pk_dim_product PRIMARY KEY (product_id) RELY
) CLUSTER BY (product_id)
COMMENT 'Product dimension';

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.dim_customer (
  customer_id       BIGINT  NOT NULL COMMENT 'Customer surrogate key',
  customer_name     STRING           COMMENT 'Customer display name',
  email             STRING           COMMENT 'Customer email',
  attributes        STRING           COMMENT 'Semi-structured attributes (JSON)',
  is_active         STRING           COMMENT 'Active flag',
  loyalty_tier      STRING           COMMENT 'Loyalty tier',
  marketing_segment STRING           COMMENT 'Marketing segment',
  updated_ts        TIMESTAMP        COMMENT 'Last update timestamp',
  CONSTRAINT pk_dim_customer PRIMARY KEY (customer_id) RELY
) CLUSTER BY (customer_id)
COMMENT 'Customer dimension';

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.fact_orders (
  order_id    BIGINT  NOT NULL COMMENT 'Order id',
  customer_id BIGINT           COMMENT 'FK to dim_customer',
  store_id    BIGINT           COMMENT 'FK to dim_store',
  order_ts    TIMESTAMP        COMMENT 'Order timestamp',
  status      STRING           COMMENT 'Order status',
  order_total DECIMAL(18,4)    COMMENT 'Order total amount',
  CONSTRAINT pk_fact_orders PRIMARY KEY (order_id) RELY
) CLUSTER BY (order_id)
COMMENT 'Orders fact';

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.fact_order_items (
  order_item_id BIGINT  NOT NULL COMMENT 'Order item id',
  order_id      BIGINT           COMMENT 'FK to fact_orders',
  product_id    BIGINT           COMMENT 'FK to dim_product',
  qty           INT              COMMENT 'Quantity',
  amount        DECIMAL(18,2)    COMMENT 'Line amount (NOTE: reduced scale vs source)',
  discount      DECIMAL(18,4)    COMMENT 'Line discount',
  CONSTRAINT pk_fact_order_items PRIMARY KEY (order_item_id) RELY
) CLUSTER BY (order_item_id)
COMMENT 'Order items fact';

CREATE OR REPLACE TABLE fevm_ps_dr_us_east_2_catalog.mig_target.agg_daily_sales (
  store_id    BIGINT        COMMENT 'FK to dim_store',
  sales_date  DATE          COMMENT 'Sales date',
  revenue     DECIMAL(18,2) COMMENT 'Daily revenue',
  order_count BIGINT        COMMENT 'Daily order count'
) CLUSTER BY (store_id, sales_date)
COMMENT 'Gold daily sales aggregate';
