-- PILOT TARGET (Databricks) — mig_target.dim_customer   [migrated from RETAIL.SOURCE.DIM_CUSTOMER]
-- Several realistic migration defects on one table:
--   S3  semi_structured : ATTRIBUTES (VARIANT) re-serialized with keys reordered (benign)
--   S8  upstream_drift   : MARKETING_SEGMENT stale for every 25th customer (older snapshot)
--   S9  null_boolean     : IS_ACTIVE 'Y'/'N' -> 'true'/'false'; EMAIL NULL -> '' (empty string)
--   S10 genuine/provenance: LOYALTY_TIER fabricated in target though source is NULL

CREATE TABLE IF NOT EXISTS fevm_ps_dr_us_east_2_catalog.mig_target.dim_customer (
  customer_id       BIGINT NOT NULL COMMENT 'Customer surrogate key',
  customer_name     STRING          COMMENT 'Customer display name',
  email             STRING          COMMENT 'Customer email',
  attributes        STRING          COMMENT 'Semi-structured attributes (JSON)',
  is_active         STRING          COMMENT 'Active flag',
  loyalty_tier      STRING          COMMENT 'Loyalty tier',
  marketing_segment STRING          COMMENT 'Marketing segment',
  updated_ts        TIMESTAMP       COMMENT 'Last update timestamp',
  CONSTRAINT pk_dim_customer PRIMARY KEY (customer_id) RELY
) CLUSTER BY (customer_id)
COMMENT 'Customer dimension (migrated)';

INSERT INTO fevm_ps_dr_us_east_2_catalog.mig_target.dim_customer
SELECT
  CAST(customer_id AS BIGINT) AS customer_id,
  customer_name,
  coalesce(email, '')         AS email,                       -- S9: NULL -> empty string
  concat('{"channel":"', get_json_object(attributes, '$.channel'),
         '","segment":"', get_json_object(attributes, '$.segment'), '"}') AS attributes,  -- S3: key reorder
  CASE WHEN is_active = 'Y' THEN 'true' ELSE 'false' END AS is_active,     -- S9: Y/N -> true/false
  element_at(array('Bronze','Silver','Gold'), CAST((customer_id % 3) + 1 AS INT)) AS loyalty_tier,  -- S10: fabricated
  CASE WHEN customer_id % 25 = 0 THEN 'STALE' ELSE marketing_segment END AS marketing_segment,      -- S8: stale
  CAST(date_sub(current_date(), 10) AS TIMESTAMP) AS updated_ts
FROM fevm_ps_dr_us_east_2_catalog.mig_source_sim.dim_customer;
