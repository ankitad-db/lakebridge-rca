-- PILOT SOURCE (Snowflake) — RETAIL.SOURCE.DIM_STORE
-- Authentic Snowflake-dialect DDL + seed. Origin system for the pilot (not executed
-- on Databricks). Declared types feed the RCA's source-type checks.

CREATE SCHEMA IF NOT EXISTS RETAIL.SOURCE;

CREATE OR REPLACE TABLE RETAIL.SOURCE.DIM_STORE (
  STORE_ID   NUMBER(38,0) NOT NULL,
  STORE_NAME VARCHAR(200),
  REGION     VARCHAR(50),
  STORE_TZ   VARCHAR(64),
  CONSTRAINT PK_DIM_STORE PRIMARY KEY (STORE_ID)
)
CLUSTER BY (STORE_ID)
COMMENT = 'Store dimension (source of truth). Clean 1:1 migration expected.';

INSERT INTO RETAIL.SOURCE.DIM_STORE (STORE_ID, STORE_NAME, REGION, STORE_TZ)
SELECT
  SEQ4() + 1                                                                        AS STORE_ID,
  'Store_' || (SEQ4() + 1)                                                          AS STORE_NAME,
  DECODE(MOD(SEQ4(), 3), 0, 'APAC', 1, 'EMEA', 'AMER')                              AS REGION,
  DECODE(MOD(SEQ4(), 3), 0, 'Asia/Kolkata', 1, 'Europe/London', 'America/New_York') AS STORE_TZ
FROM TABLE(GENERATOR(ROWCOUNT => 5));
