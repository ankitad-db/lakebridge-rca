-- DEEP-DIAMOND · SOURCE (Snowflake) — arm C leaf  (ANALYTICS.SOURCE.LEAF_E)
-- Declared source types + true business rules the RCA's code-aware pass reads:
--   AMOUNT     = NUMBER(18,4)  (full precision — migration must preserve the scale)
--   GROSS_AMOUNT = NUMBER(18,4)
--   NET_AMOUNT = NUMBER(18,4) = round(GROSS_AMOUNT * 0.90, 2)   <- 10% loyalty discount.
--   QTY        = NUMBER(38,0)
-- Arm C carries NO sku column. Any other net factor is a business regression.

CREATE OR REPLACE TABLE ANALYTICS.SOURCE.LEAF_E (
  A_ID         NUMBER(38,0) NOT NULL,
  AMOUNT       NUMBER(18,4),
  GROSS_AMOUNT NUMBER(18,4),
  NET_AMOUNT   NUMBER(18,4),
  QTY          NUMBER(38,0),
  CONSTRAINT PK_LEAF_E PRIMARY KEY (A_ID)
)
COMMENT 'Arm C leaf. AMOUNT = NUMBER(18,4) (preserve scale). NET_AMOUNT = GROSS_AMOUNT * 0.90 (10% loyalty discount).';
