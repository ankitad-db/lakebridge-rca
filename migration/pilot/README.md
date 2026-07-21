# Pilot migration scripts (Snowflake → Databricks)

Authentic, per-object migration scripts for the retail **pilot** — the representative
subset a real Snowflake→Databricks engagement migrates first. Two views of the same six
objects:

```
pilot/
  source_snowflake/     # ORIGIN — authentic Snowflake-dialect objects (DDL + seed)
    dim_store.sql  dim_product.sql  dim_customer.sql
    fact_orders.sql  fact_order_items.sql  agg_daily_sales.sql
  target_databricks/    # MIGRATED — Databricks scripts (DDL + load transform), with defects
    dim_store.sql  dim_product.sql  dim_customer.sql
    fact_orders.sql  fact_order_items.sql  agg_daily_sales.sql
  table_manifest.yml    # maps each target <-> its source & target script (for the RCA skill)
```

## What these are (and aren't)
- **Source scripts** are true Snowflake dialect (`NUMBER(18,4)`, `TIMESTAMP_LTZ`, `VARIANT`,
  `SEQUENCE`, `GENERATOR`, `PARSE_JSON`, `IFF`, `DATEADD`, …). They document the origin schema
  and are **not executed on Databricks**.
- **Target scripts** are the migrated Databricks SQL (DDL + `INSERT … SELECT` transform). They
  read the source from the runnable simulation `mig_source_sim` so the pilot works without a
  live Snowflake. In a real engagement the `FROM` points at your source; **Lakebridge manages
  the source connection** for transpile/reconcile, so no connection setup lives here.
- Each target carries the same deliberately-injected defects as the deployed pipeline, keyed to
  the scenarios in [`../scenarios.md`](../scenarios.md) (S1–S10) so the RCA can be validated.

## How the RCA uses them (code-aware correlation)
Point the `rca-recon` skill (or the CLI) at these scripts and every finding is confirmed from
the actual code, not just the data:
- `source_snowflake/` → **declared source types** (e.g. `fact_order_items.amount NUMBER(18,4)`
  confirms the S1 scale loss; `fact_orders.order_ts TIMESTAMP_LTZ` confirms the S2 tz normalization).
- `target_databricks/` → **per-column transforms** (`MAKE_INTERVAL` proves the +5:30 shift;
  `WHERE order_id <= 480` proves the S6 watermark; `round(sum,·,0)` proves the S5 rounding).

Wire it via the manifest (recommended):
```bash
python -m rca_engine.cli --recon-id <ID> --recon-catalog <cat> --recon-schema reconcile \
  --warehouse-id <WID> --table-manifest migration/pilot/table_manifest.yml
```
or via folder scans (`--source-scripts migration/pilot/source_snowflake --transpiled-output
migration/pilot/target_databricks`), or the equivalent keys in `skill/rca-recon/config.yml`.

## Object map
| Object | Source (Snowflake) | Migration defect in target | Scenario |
|---|---|---|---|
| `dim_store` | clean dimension | none (clean baseline) | C1 |
| `dim_product` | `UNIT_PRICE NUMBER(18,4)` | SKU lower + trailing space | S4 |
| `dim_customer` | `VARIANT`, `Y/N`, NULL tier, `TIMESTAMP_LTZ` | JSON reorder / Y-N→bool / NULL→'' / fabricated tier / stale segment | S3, S8, S9, S10 |
| `fact_orders` | `ORDER_TS TIMESTAMP_LTZ` | +5:30 tz shift + watermark filter | S2, S6 |
| `fact_order_items` | `AMOUNT NUMBER(18,4)` | scale→2 + duplicate fan-out | S1, S7 |
| `agg_daily_sales` | exact `NUMBER(18,2)` SUM | `ROUND(sum,0)` | S5 |

> The comprehensive edge-case coverage (overflow, non-constant tz, schema diff, week-start,
> sentinel/boolean, etc.) lives in [`../edge_cases/`](../edge_cases) and [`../scenarios.yaml`](../scenarios.yaml).
