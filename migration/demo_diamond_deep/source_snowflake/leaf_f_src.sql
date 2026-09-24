-- DEEP-DIAMOND · SOURCE (Snowflake) — arm D leaf  (ANALYTICS.SOURCE.LEAF_F)
-- Declared source types + true business rules the RCA's code-aware pass reads:
--   AMOUNT     = NUMBER(18,4)  (full precision — migration must preserve the scale)
--   GROSS_AMOUNT = NUMBER(18,4)
--   NET_AMOUNT = NUMBER(18,4) = round(GROSS_AMOUNT * 0.90, 2)   <- 10% loyalty discount.
--   SKU        = VARCHAR       original case, 'SKU-<id>' (preserve case; no trailing spaces).
--   QTY        = NUMBER(38,0)
-- Arm D carries the sku column. Any other net factor is a business regression; any change of
-- case/whitespace on SKU is a string-format regression.

CREATE OR REPLACE TABLE ANALYTICS.SOURCE.LEAF_F (
  A_ID         NUMBER(38,0) NOT NULL,
  AMOUNT       NUMBER(18,4),
  GROSS_AMOUNT NUMBER(18,4),
  NET_AMOUNT   NUMBER(18,4),
  SKU          VARCHAR(50),
  QTY          NUMBER(38,0),
  CONSTRAINT PK_LEAF_F PRIMARY KEY (A_ID)
)
COMMENT 'Arm D leaf. AMOUNT = NUMBER(18,4). NET_AMOUNT = GROSS_AMOUNT * 0.90 (10% discount). SKU = original-case ''SKU-<id>''.';
