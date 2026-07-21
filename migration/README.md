# Retail migration test bed (Snowflake -> Databricks)

A realistic, runnable migration scenario used to exercise the automated RCA
skill. A simulated Snowflake source (`mig_source_sim`) is migrated into a
Databricks medallion target (`mig_target`) with **10 deliberately injected
defects** spanning code-translation, environment/type, pipeline, and genuine
upstream-data differences. Lakebridge `reconcile` then compares the two and the
RCA engine explains every mismatch.

## Namespaces

All objects live in the existing catalog `fevm_ps_dr_us_east_2_catalog`
(catalog creation on this workspace needs a managed location), using schemas:

| Schema | Role |
|--------|------|
| `mig_source_sim` | Simulated Snowflake source (source of truth) |
| `mig_target` | Migrated Databricks target (dims, facts, gold) |
| `reconcile` | Lakebridge reconcile metadata + output tables |

## Layout

```
migration/
  run_sql.py                 # helper: run a .sql file on a SQL warehouse via the CLI
  source_sql/01_source_ddl.sql          # Snowflake-dialect DDL (reference only)
  source_sim/02_create_source_sim.sql   # runnable source + seed data
  target/10_target_ddl.sql              # Databricks target DDL (types, PKs, clustering)
  pipeline/20_bronze_ingest.py          # bronze raw ingest (notebook)
  pipeline/21_silver_transform.sql      # silver dims/facts (injects most defects)
  pipeline/22_gold_aggregate.sql        # gold daily aggregate (transpilation defect)
  pipeline/23_incremental_merge.py      # incremental MERGE (watermark defect)
  pipeline/databricks.yml               # Asset Bundle Job orchestrating the above
  recon/30_reconcile_config.json        # Lakebridge table-mapping config (all pairs)
  scenarios.md / scenarios.yaml         # ground-truth manifest / machine-readable oracle
  edge_cases/                           # comprehensive edge-case source + target tables
  pilot/                                # authentic pilot migration scripts (see below)
```

## Pilot migration scripts (`pilot/`)

Authentic, per-object **Snowflake source** and **migrated Databricks target** scripts for the
retail pilot — the code-aware inputs for the RCA. `source_snowflake/` holds true Snowflake-dialect
DDL/seed (declared types like `NUMBER(18,4)`, `TIMESTAMP_LTZ`, `VARIANT`); `target_databricks/`
holds the migrated `INSERT … SELECT` transforms (carrying the injected defects). See
[`pilot/README.md`](pilot/README.md). Lakebridge owns the source connection for reconcile, so no
connection setup is included here.

## Setup (manual, in order)

Warehouse id used below: `4c79c6902dd2bbc2`. Profile: `ps-dr-east`.

1. **Source**: `python run_sql.py --file source_sim/02_create_source_sim.sql --warehouse-id 4c79c6902dd2bbc2 --profile ps-dr-east`
2. **Target schema/DDL**: `python run_sql.py --file target/10_target_ddl.sql ...`
3. **Silver + gold** (the migration pipeline):
   `python run_sql.py --file pipeline/21_silver_transform.sql ...` then `22_gold_aggregate.sql`.
   (Or deploy the Job: `databricks bundle deploy -t dev -p ps-dr-east` and run it.)
4. **Configure Lakebridge reconcile** (one time):
   `databricks labs lakebridge configure-reconcile -p ps-dr-east`
   (source dialect = databricks, report = all, source catalog/schema =
   `fevm_ps_dr_us_east_2_catalog`/`mig_source_sim`, target = same catalog/`mig_target`,
   metadata = same catalog/`reconcile`/`reconcile_volume`).
5. **Table mappings**: upload `recon/30_reconcile_config.json` to the install
   folder as `recon_config_databricks_fevm_ps_dr_us_east_2_catalog_all.json`.
6. **Run reconcile**: `databricks labs lakebridge reconcile -p ps-dr-east`.
   Output lands in `fevm_ps_dr_us_east_2_catalog.reconcile` (`main`, `metrics`, `details`).

## What to expect

See `scenarios.md` for the exact defect in each table and the verdict the RCA
skill should return. After reconcile completes, invoke the `rca-recon` Genie
Code skill with the `recon_id` to generate and run the RCA notebook.
