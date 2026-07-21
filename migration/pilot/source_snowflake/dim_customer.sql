-- PILOT SOURCE (Snowflake) — RETAIL.SOURCE.DIM_CUSTOMER
-- The trickiest object to migrate: VARIANT attributes, 'Y'/'N' flag, a NULL-in-source
-- LOYALTY_TIER, and a session-relative TIMESTAMP_LTZ. Uses a SEQUENCE for the surrogate key.

CREATE SCHEMA IF NOT EXISTS RETAIL.SOURCE;

CREATE SEQUENCE IF NOT EXISTS RETAIL.SOURCE.SEQ_CUSTOMER START = 1 INCREMENT = 1;

CREATE OR REPLACE TABLE RETAIL.SOURCE.DIM_CUSTOMER (
  CUSTOMER_ID       NUMBER(38,0) NOT NULL DEFAULT RETAIL.SOURCE.SEQ_CUSTOMER.NEXTVAL,
  CUSTOMER_NAME     VARCHAR(200),
  EMAIL             VARCHAR(320),
  ATTRIBUTES        VARIANT,
  IS_ACTIVE         VARCHAR(1),
  LOYALTY_TIER      VARCHAR(20),
  MARKETING_SEGMENT VARCHAR(10),
  UPDATED_TS        TIMESTAMP_LTZ(9),
  CONSTRAINT PK_DIM_CUSTOMER PRIMARY KEY (CUSTOMER_ID)
)
COMMENT = 'Customer dimension. ATTRIBUTES=VARIANT (JSON), IS_ACTIVE=Y/N, LOYALTY_TIER often NULL, UPDATED_TS=TIMESTAMP_LTZ.';

INSERT INTO RETAIL.SOURCE.DIM_CUSTOMER
  (CUSTOMER_ID, CUSTOMER_NAME, EMAIL, ATTRIBUTES, IS_ACTIVE, LOYALTY_TIER, MARKETING_SEGMENT, UPDATED_TS)
SELECT
  SEQ4() + 1                                                                        AS CUSTOMER_ID,
  'Customer_' || (SEQ4() + 1)                                                       AS CUSTOMER_NAME,
  IFF(MOD(SEQ4() + 1, 20) = 0, NULL, 'cust' || (SEQ4() + 1) || '@example.com')      AS EMAIL,
  PARSE_JSON('{"segment":"' || DECODE(MOD(SEQ4(),3),0,'A',1,'B','C') ||
             '","channel":"' || DECODE(MOD(SEQ4(),3),0,'web',1,'store','mobile') || '"}') AS ATTRIBUTES,
  IFF(MOD(SEQ4() + 1, 7) = 0, 'N', 'Y')                                             AS IS_ACTIVE,
  NULL                                                                              AS LOYALTY_TIER,
  DECODE(MOD(SEQ4(),3),0,'A',1,'B','C')                                             AS MARKETING_SEGMENT,
  CURRENT_TIMESTAMP()                                                               AS UPDATED_TS
FROM TABLE(GENERATOR(ROWCOUNT => 100));
