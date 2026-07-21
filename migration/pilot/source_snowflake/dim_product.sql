-- PILOT SOURCE (Snowflake) — RETAIL.SOURCE.DIM_PRODUCT
-- UNIT_PRICE is NUMBER(18,4): scale 4 must be preserved on migration.

CREATE SCHEMA IF NOT EXISTS RETAIL.SOURCE;

CREATE OR REPLACE TABLE RETAIL.SOURCE.DIM_PRODUCT (
  PRODUCT_ID   NUMBER(38,0) NOT NULL,
  SKU          VARCHAR(40),
  PRODUCT_NAME VARCHAR(200),
  CATEGORY     VARCHAR(50),
  UNIT_PRICE   NUMBER(18,4),
  CONSTRAINT PK_DIM_PRODUCT PRIMARY KEY (PRODUCT_ID)
)
COMMENT = 'Product dimension. SKU is upper-case canonical; UNIT_PRICE scale 4.';

INSERT INTO RETAIL.SOURCE.DIM_PRODUCT (PRODUCT_ID, SKU, PRODUCT_NAME, CATEGORY, UNIT_PRICE)
SELECT
  SEQ4() + 1                                                                          AS PRODUCT_ID,
  'SKU-' || LPAD(TO_VARCHAR(SEQ4() + 1), 4, '0')                                      AS SKU,
  'Product ' || (SEQ4() + 1)                                                          AS PRODUCT_NAME,
  DECODE(MOD(SEQ4(), 5), 0,'Electronics',1,'Home',2,'Grocery',3,'Apparel','Toys')     AS CATEGORY,
  CAST(ROUND(10 + (SEQ4() + 1) * 3.25, 4) AS NUMBER(18,4))                             AS UNIT_PRICE
FROM TABLE(GENERATOR(ROWCOUNT => 30));
