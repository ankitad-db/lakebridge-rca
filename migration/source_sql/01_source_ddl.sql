-- ORIGINAL SNOWFLAKE-DIALECT DDL (reference only -- not executed on Databricks).
-- This documents the "source of truth" schema as it exists in Snowflake and the
-- type-mapping decisions the migration must get right. The runnable Databricks
-- simulation of this source lives in ../source_sim/02_create_source_sim.sql.

CREATE SCHEMA IF NOT EXISTS RETAIL.SOURCE;

CREATE OR REPLACE TABLE RETAIL.SOURCE.DIM_STORE (
  STORE_ID    NUMBER(38,0) NOT NULL,
  STORE_NAME  VARCHAR,
  REGION      VARCHAR,
  STORE_TZ    VARCHAR,
  PRIMARY KEY (STORE_ID)
);

CREATE OR REPLACE TABLE RETAIL.SOURCE.DIM_PRODUCT (
  PRODUCT_ID   NUMBER(38,0) NOT NULL,
  SKU          VARCHAR,
  PRODUCT_NAME VARCHAR,
  CATEGORY     VARCHAR,
  UNIT_PRICE   NUMBER(18,4),          -- maps to Databricks DECIMAL(18,4)
  PRIMARY KEY (PRODUCT_ID)
);

CREATE OR REPLACE TABLE RETAIL.SOURCE.DIM_CUSTOMER (
  CUSTOMER_ID       NUMBER(38,0) NOT NULL,
  CUSTOMER_NAME     VARCHAR,
  EMAIL             VARCHAR,
  ATTRIBUTES        VARIANT,          -- semi-structured; maps to STRING(JSON)/STRUCT
  IS_ACTIVE         VARCHAR,          -- 'Y'/'N' in source; must map to BOOLEAN carefully
  LOYALTY_TIER      VARCHAR,          -- often NULL in source (not populated upstream)
  MARKETING_SEGMENT VARCHAR,
  UPDATED_TS        TIMESTAMP_LTZ,    -- session-tz relative; normalize to UTC on load
  PRIMARY KEY (CUSTOMER_ID)
);

CREATE OR REPLACE TABLE RETAIL.SOURCE.FACT_ORDERS (
  ORDER_ID    NUMBER(38,0) NOT NULL,
  CUSTOMER_ID NUMBER(38,0),
  STORE_ID    NUMBER(38,0),
  ORDER_TS    TIMESTAMP_LTZ,          -- normalize to UTC on load
  STATUS      VARCHAR,
  ORDER_TOTAL NUMBER(18,4),
  PRIMARY KEY (ORDER_ID)
);

CREATE OR REPLACE TABLE RETAIL.SOURCE.FACT_ORDER_ITEMS (
  ORDER_ITEM_ID NUMBER(38,0) NOT NULL,
  ORDER_ID      NUMBER(38,0),
  PRODUCT_ID    NUMBER(38,0),
  QTY           NUMBER(38,0),
  AMOUNT        NUMBER(18,4),         -- PRESERVE scale: do NOT map to DOUBLE/lower scale
  DISCOUNT      NUMBER(18,4),
  PRIMARY KEY (ORDER_ITEM_ID)
);

-- Gold aggregate (business logic that must be transpiled faithfully to Spark SQL).
CREATE OR REPLACE TABLE RETAIL.SOURCE.AGG_DAILY_SALES AS
SELECT
  STORE_ID,
  TO_DATE(ORDER_TS)                       AS SALES_DATE,
  CAST(SUM(ORDER_TOTAL) AS NUMBER(18,2))  AS REVENUE,
  COUNT(*)                                AS ORDER_COUNT
FROM RETAIL.SOURCE.FACT_ORDERS
GROUP BY STORE_ID, TO_DATE(ORDER_TS);
