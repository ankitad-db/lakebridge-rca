-- DEMO DIAMOND · SOURCE (Snowflake) — RETAIL.SOURCE.ORDERS
-- Declared source types the RCA's code-aware pass reads to reason about migration risk:
--   ORDER_TOTAL = NUMBER(18,4)  -> high precision; a target cast to DECIMAL(18,2) loses scale.
--   ORDER_TS    = TIMESTAMP_LTZ -> session-tz relative; must be normalized to UTC on load.
--   SKU         = VARCHAR       -> case/whitespace sensitive; must round-trip exactly.

CREATE SCHEMA IF NOT EXISTS RETAIL.SOURCE;

CREATE OR REPLACE TABLE RETAIL.SOURCE.ORDERS (
  ORDER_ID    NUMBER(38,0) NOT NULL,
  CUSTOMER_ID NUMBER(38,0),
  ORDER_TS    TIMESTAMP_LTZ(9),
  ORDER_TOTAL NUMBER(18,4),
  SKU         VARCHAR(40),
  STATUS      VARCHAR(20),
  REGION      VARCHAR(10),
  CONSTRAINT PK_ORDERS PRIMARY KEY (ORDER_ID)
)
COMMENT = 'Orders source. ORDER_TS = TIMESTAMP_LTZ (normalize to UTC); ORDER_TOTAL = NUMBER(18,4) (keep 4dp).';

INSERT INTO RETAIL.SOURCE.ORDERS (ORDER_ID, CUSTOMER_ID, ORDER_TS, ORDER_TOTAL, SKU, STATUS, REGION)
SELECT
  SEQ4() + 1                                                                 AS ORDER_ID,
  MOD(SEQ4(), 100) + 1                                                       AS CUSTOMER_ID,
  DATEADD('hour', MOD(SEQ4(), 24), '2024-01-01 00:00:00'::TIMESTAMP_LTZ)     AS ORDER_TS,
  CAST(20 + MOD(SEQ4(), 500) * 1.7777 AS NUMBER(18,4))                       AS ORDER_TOTAL,
  'SKU-' || LPAD(MOD(SEQ4(), 50)::VARCHAR, 4, '0')                           AS SKU,
  DECODE(MOD(SEQ4(), 4), 0,'COMPLETED',1,'SHIPPED',2,'PENDING','RETURNED')   AS STATUS,
  DECODE(MOD(SEQ4(), 4), 0,'NA',1,'EU',2,'APAC','LATAM')                     AS REGION
FROM TABLE(GENERATOR(ROWCOUNT => 500));
