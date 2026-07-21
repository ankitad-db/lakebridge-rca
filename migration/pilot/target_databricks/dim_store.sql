-- PILOT TARGET (Databricks) — mig_target.dim_store   [migrated from RETAIL.SOURCE.DIM_STORE]
-- Type mapping: NUMBER(38,0)->BIGINT, VARCHAR->STRING. Clean passthrough (no defect).
-- Reads the simulated source (mig_source_sim). In a live engagement the FROM points at
-- the Lakebridge-configured source (reconcile owns the source connection).

CREATE TABLE IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_target.dim_store (
  store_id   BIGINT NOT NULL COMMENT 'Store surrogate key',
  store_name STRING          COMMENT 'Store display name',
  region     STRING          COMMENT 'Sales region',
  store_tz   STRING          COMMENT 'Store timezone (IANA)',
  CONSTRAINT pk_dim_store PRIMARY KEY (store_id) RELY
) CLUSTER BY (store_id)
COMMENT 'Store dimension (migrated)';

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.dim_store
SELECT CAST(store_id AS BIGINT) AS store_id, store_name, region, store_tz
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_store;
