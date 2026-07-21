-- PILOT SOURCE (Snowflake) — RETAIL.SOURCE.FACT_ORDER_ITEMS
-- AMOUNT is NUMBER(18,4): scale 4 MUST be preserved (do NOT migrate to DOUBLE / lower scale).

CREATE SCHEMA IF NOT EXISTS RETAIL.SOURCE;

CREATE OR REPLACE TABLE RETAIL.SOURCE.FACT_ORDER_ITEMS (
  ORDER_ITEM_ID NUMBER(38,0) NOT NULL,
  ORDER_ID      NUMBER(38,0),
  PRODUCT_ID    NUMBER(38,0),
  QTY           NUMBER(38,0),
  AMOUNT        NUMBER(18,4),
  DISCOUNT      NUMBER(18,4),
  CONSTRAINT PK_FACT_ORDER_ITEMS PRIMARY KEY (ORDER_ITEM_ID),
  CONSTRAINT FK_ITEMS_ORDER FOREIGN KEY (ORDER_ID) REFERENCES RETAIL.SOURCE.FACT_ORDERS(ORDER_ID)
)
COMMENT = 'Order items fact. Three lines per order; AMOUNT scale 4 must be preserved.';

INSERT INTO RETAIL.SOURCE.FACT_ORDER_ITEMS (ORDER_ITEM_ID, ORDER_ID, PRODUCT_ID, QTY, AMOUNT, DISCOUNT)
SELECT
  o.ORDER_ID * 10 + s.K                                                             AS ORDER_ITEM_ID,
  o.ORDER_ID                                                                        AS ORDER_ID,
  MOD(o.ORDER_ID + s.K, 30) + 1                                                     AS PRODUCT_ID,
  s.K + 1                                                                           AS QTY,
  CAST(ROUND(MOD(o.ORDER_ID + s.K, 200) * 1.2345 + 0.6789, 4) AS NUMBER(18,4))      AS AMOUNT,
  CAST(ROUND(s.K * 0.05, 4) AS NUMBER(18,4))                                        AS DISCOUNT
FROM RETAIL.SOURCE.FACT_ORDERS o,
     LATERAL (SELECT SEQ4() AS K FROM TABLE(GENERATOR(ROWCOUNT => 3))) s;
