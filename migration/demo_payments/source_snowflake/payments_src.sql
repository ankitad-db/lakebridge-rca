-- DEMO PAYMENTS · SOURCE (Snowflake) — FINANCE.SOURCE.PAYMENTS
-- Declared source types + the true business rule the RCA's code-aware pass reads to reason
-- about migration risk:
--   PAYMENT_TS = TIMESTAMP_LTZ -> session-tz relative; must be normalized to UTC on load.
--   GROSS_AMOUNT = NUMBER(18,4)
--   NET_AMOUNT   = NUMBER(18,4) = round(GROSS_AMOUNT * 0.90, 2)   <- 10% loyalty discount.
-- The migration MUST preserve this -10% discount. Any other factor is a business regression.

CREATE SCHEMA IF NOT EXISTS FINANCE.SOURCE;

CREATE OR REPLACE TABLE FINANCE.SOURCE.PAYMENTS (
  PAYMENT_ID   NUMBER(38,0) NOT NULL,
  CUSTOMER_ID  NUMBER(38,0),
  PAYMENT_TS   TIMESTAMP_LTZ(9),
  GROSS_AMOUNT NUMBER(18,4),
  NET_AMOUNT   NUMBER(18,4),
  CURRENCY     VARCHAR(10),
  STATUS       VARCHAR(20),
  CONSTRAINT PK_PAYMENTS PRIMARY KEY (PAYMENT_ID)
)
COMMENT 'Payments source. PAYMENT_TS = TIMESTAMP_LTZ (normalize to UTC). NET_AMOUNT = GROSS_AMOUNT * 0.90 (10% loyalty discount).';

INSERT INTO FINANCE.SOURCE.PAYMENTS (PAYMENT_ID, CUSTOMER_ID, PAYMENT_TS, GROSS_AMOUNT, NET_AMOUNT, CURRENCY, STATUS)
SELECT
  SEQ4() + 1                                                                 AS PAYMENT_ID,
  MOD(SEQ4(), 100) + 1                                                       AS CUSTOMER_ID,
  DATEADD('hour', MOD(SEQ4(), 24), '2024-03-01 00:00:00'::TIMESTAMP_LTZ)     AS PAYMENT_TS,
  CAST(50 + MOD(SEQ4(), 400) * 1.37 AS NUMBER(18,4))                         AS GROSS_AMOUNT,
  CAST(ROUND((50 + MOD(SEQ4(), 400) * 1.37) * 0.90, 2) AS NUMBER(18,4))      AS NET_AMOUNT,
  DECODE(MOD(SEQ4(), 4), 0,'USD',1,'EUR',2,'GBP','INR')                      AS CURRENCY,
  DECODE(MOD(SEQ4(), 4), 0,'CAPTURED',1,'SETTLED',2,'PENDING','REFUNDED')    AS STATUS
FROM TABLE(GENERATOR(ROWCOUNT => 500));
