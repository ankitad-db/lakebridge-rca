# Reconcile configs

Lakebridge `reconcile` table configs for the migration test bed. Pick one when you run
`databricks labs lakebridge reconcile` (or point the RCA skill's `recon_config` at it). Reconcile
loads the config from the workspace install folder as
`~/.lakebridge/recon_config_databricks_<catalog>_all.json`, so "running a config" means importing
that file, e.g.:

```bash
databricks workspace import \
  "/Users/<you>/.lakebridge/recon_config_databricks_fevm_ps_dr_us_east_2_catalog_all.json" \
  --file migration/recon/33_reconcile_config_full.json --format RAW --overwrite -p ps-dr-east
databricks labs lakebridge reconcile -p ps-dr-east
```

| File | Purpose |
|---|---|
| [`30_reconcile_config.json`](30_reconcile_config.json) | **Baseline.** Plain `source_name`/`target_name`/`join_columns` only — no mappings, transforms, or thresholds. Every injected defect surfaces raw, so it backs the calibrated scenario oracle (`../scenarios.yaml`, 22 scenarios) and the unit/integration tests. Start here. |
| [`31_reconcile_config_advanced.json`](31_reconcile_config_advanced.json) | **Feature demo / RCA stress test.** Exercises most reconcile customizations so we can verify the RCA correctly *reads and reasons about* a real-world, tuned config. |
| [`32_reconcile_config_edge.json`](32_reconcile_config_edge.json) | **Edge-only run.** The 9 edge tables (`edge_numeric`, `edge_events`, `edge_string`, `dim_supplier`, `dim_config`, `fact_inventory`, `dim_flag`, `fact_payments`, `agg_weekly_sales`) that reconcile cleanly with plain configs. Excludes `edge_geo` (see caveat below). |
| [`33_reconcile_config_full.json`](33_reconcile_config_full.json) | **Everything in one run.** All 16 pairs (6 pilot + 10 edge), with `edge_geo` handled via `column_mapping` so reconcile does not abort. Recommended for a single comprehensive `recon_id`. |

## ⚠️ Caveat: renamed columns abort `report_type: all`

`edge_geo` renames `country` → `country_name` in the target (scenario **E4**). With
`report_type: all`, Lakebridge's data comparison requires matching column names and raises
`ColumnMismatchException` — which aborts the **entire** run, not just that table. Two ways to
handle it, both real-world valid:
- **Exclude it** (baseline `32_…edge.json`): reconcile the rest; treat the rename as a known
  schema diff the RCA reports separately.
- **Map it** (`33_…full.json` / `31_…advanced.json`): add `column_mapping`
  `country → country_name` so reconcile compares by value; only the residual `lat` DECIMAL→DOUBLE
  diff remains.

## Real recon runs on this workspace

Produced by actually running `databricks labs lakebridge reconcile` against
`fevm_ps_dr_us_east_2_catalog` (source `mig_source_sim` → target `mig_target`, dialect
`databricks`). Point the RCA CLI/skill/app at any of these `recon_id`s:

| recon_id | Config | Pairs | Tables with diffs |
|---|---|---|---|
| `0fe6053f134846948490952e94b747bf` | pilot (`30_…`) | 6 | 5 |
| `e8330139f4144001a5ba218ba0689b28` | edge (`32_…`) | 9 | 8 |
| `eedae7b85e034c63b6b5fa96e1d044e5` | full (`33_…`) | 16 | 14 |

## Is the recon run customizable? Yes — and the RCA now understands it

Reconcile can be tuned per table. The advanced config uses the main levers, and the RCA engine
ingests each one (see `rca_engine/lakebridge.py`) and reflects it as `recon_config` evidence on
the relevant finding (see `rca_engine/classify.py::_apply_recon_config_features`). As a tester,
each feature below is chosen to change what recon reports and to prove the RCA interprets it:

| Feature (config key) | Where it's used | What it does to recon | How the RCA interprets it |
|---|---|---|---|
| `join_columns` | every table | Keys used to align rows | Column-level drill-down joins on these |
| `column_mapping` | `edge_geo` (`country`→`country_name`) | Compares a **renamed** column by value instead of flagging a schema diff | Adds evidence "compared source `country` to target `country_name` despite rename"; the residual (DECIMAL→DOUBLE on `lat`) still surfaces |
| `transformations` | `dim_product.sku` (`trim(lower(...))`), `dim_customer.email` (`coalesce(...,'')`) | Normalizes a **known-benign** difference on the compare side so it no longer mismatches | If a mismatch still surfaces, RCA notes the transform and treats the remainder as a **real residual**, not the normalized part |
| `column_thresholds` | `fact_order_items.amount`, `dim_product.unit_price`, `agg_daily_sales.revenue`, `edge_geo.lat` | Numeric **tolerance**: rows within bound count as matched | RCA notes the tolerance; a row still flagged **exceeded** it, so it is a genuine over-threshold diff |
| `table_thresholds` | `fact_orders` (0–5 mismatches, `model: mismatch`) | Allows a small **row-count** mismatch budget before failing the table | Signals which tables have an accepted small drift budget |
| `filters` | `fact_orders` (`order_ts >= '2026-01-01'`) | Restricts the compared window on **both** sides | Feeds the notebook's date-range validation and explains scope |
| `select_columns` | `dim_store` (id/name/region) | Compares only a **subset** of columns | Narrows the compared surface |
| `drop_columns` | `dim_customer` (`updated_ts`) | **Excludes** a volatile column from comparison | Prevents false positives on load-time timestamps |
| `jdbc_reader_options` | `fact_orders` (partitioning + fetch size) | Tunes **read parallelism** from the source JDBC | Performance-only; no effect on verdicts |

### Tester note — how the advanced config shifts expected results
- `dim_product`: `sku` normalized (S4 suppressed) and `unit_price` within tolerance ⇒ this table
  should now be **clean** under the advanced config.
- `fact_order_items`: `amount` tolerance ±0.005 **absorbs** the scale-4→2 loss (S1) ⇒ only the
  duplicate fan-out (S7, volume) remains.
- `agg_daily_sales`: `revenue` ±0.5 tolerance is **exceeded** by the whole-unit rounding (S5) ⇒
  still flagged, with the tolerance called out as evidence.
- `edge_geo`: the rename is handled by `column_mapping`, so only the `lat` type diff logic applies.
- `dim_customer`: dropping `updated_ts` removes a benign timestamp diff; the `email` coalesce
  matches the target's NULL→'' handling (S9) so email stops mismatching, leaving S3/S8/S10.

Run the baseline config for full-coverage RCA testing; run the advanced config to validate the
skill against a realistically tuned reconcile.
