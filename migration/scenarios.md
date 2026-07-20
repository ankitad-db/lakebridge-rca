# Ground-truth scenarios (injected defects)

Each row is a deliberately injected difference between the source
(`mig_source_sim`) and the migrated target (`mig_target`). The RCA skill is
validated by checking that it produces the expected **verdict** and
**category** for each.

| ID | Table.Column | Recon signal | Category | Expected verdict | Mechanism (how it was injected) |
|----|--------------|--------------|----------|------------------|----------------------------------|
| S1 | `fact_order_items.amount` | column mismatch | type_precision | Migration-induced | Source `DECIMAL(18,4)` migrated as `DECIMAL(18,2)` -> rounding drift |
| S2 | `fact_orders.order_ts` | column mismatch | timezone | Migration-induced | Target = source + 5:30, no UTC normalization (TIMESTAMP_LTZ story) |
| S3 | `dim_customer.attributes` | column mismatch | semi_structured | Benign / expected | JSON keys reordered (channel before segment); semantically equal |
| S4 | `dim_product.sku` | column mismatch | string_format | Migration-induced | Target lower-cased + trailing whitespace |
| S5 | `agg_daily_sales.revenue` | column mismatch | transpilation | Migration-induced | `ROUND(sum,0)` half-even vs source `DECIMAL(18,2)` sum |
| S6 | `fact_orders` (rows) | missing_in_target | volume_missing | Migration-induced | Watermark drops `order_id > 480` (20 late rows) |
| S7 | `fact_order_items` (rows) | missing_in_source | volume_extra | Migration-induced | Fan-out duplicates for `order_id <= 5` (15 extra rows) |
| S8 | `dim_customer.marketing_segment` | column mismatch | upstream_drift | Genuine data difference | Source updated after extract; target holds `STALE` for every 25th customer |
| S9 | `dim_customer.is_active` / `email` | column mismatch | null_boolean | Migration-induced | `Y`/`N` -> `true`/`false`; NULL email -> empty string |
| S10 | `dim_customer.loyalty_tier` | column mismatch | upstream_drift (provenance) | Genuine data difference | Source NULL (never populated); target populated -> route to data owner, not a migration fix |

## Edge-case scenarios (comprehensive coverage)

Backed by `edge_cases/40_edge_source.sql` + `41_edge_target.sql` (same
`mig_source_sim` -> `mig_target` schemas, so one recon run covers them). These
exercise the remaining categories and edge variants for production-grade testing.

| ID | Table.Column | Category | Expected verdict | Mechanism |
|----|--------------|----------|------------------|-----------|
| E1 | `edge_numeric.v_double` | type_precision | Migration-induced | `DECIMAL(18,6)` -> `DOUBLE` binary float error |
| E2 | `edge_numeric.big_id` | type_precision | Migration-induced | `NUMBER(38,0)` -> `INT` integer overflow (32-bit wrap) |
| E3 | `edge_events.event_ts` | timezone | Needs review | offset **varies by row** -> not a single tz normalization |
| E4 | `edge_geo` (schema) | type_precision | Migration-induced | column renamed + `DECIMAL(9,6)` -> `DOUBLE` |
| E5 | `agg_weekly_sales.week_start` | env_config | Migration-induced | week-start Sunday vs Monday (`DATE_TRUNC`) |
| E6 | `dim_supplier.contact_email` | upstream_drift | Genuine data difference | target NULL where source populated (dropped upstream) |
| E7 | `dim_config.settings_json` | semi_structured | Needs review | JSON value genuinely different (not a reorder) |
| E8 | `fact_inventory.reorder_level` | null_boolean | Migration-induced | NULL replaced by sentinel `-1` |
| E9 | `dim_flag.active_flag` | null_boolean | Migration-induced | `1/0` -> `true/false` |
| E10 | `fact_payments` (rows) | volume_extra | Migration-induced | non-idempotent merge -> duplicate rows |
| E11 | `edge_string.name_ws` | string_format | Migration-induced | trailing whitespace |
| E12 | `edge_string.name_unicode` | string_format | Migration-induced | Unicode NFC vs NFD (normalize on load) |
| C1 | `dim_store` | — | — (clean) | 1:1 copy; must produce **zero** findings |

## Testing

- **`scenarios.yaml`** — machine-readable oracle (the source of truth for both harnesses below).
- **Deterministic unit tests** (`tests/`, no workspace): `pytest` drives every
  category/variant through the probes + classifier. Run: `pytest`.
- **Integration harness** (`scripts/validate_scenarios.py`): runs the full
  `analyze()` against a real recon run and checks every deployed scenario against
  the oracle. Run: `python scripts/validate_scenarios.py --recon-id <id> --warehouse-id <wid>`.

## Verdict legend

- **Migration-induced**: fix in the migration (code/type/pipeline/environment).
- **Genuine data difference**: real source/upstream difference; route to the data owner.
- **Benign / expected**: formatting-only or within tolerance.

## Notes

- Namespaces are schema-based inside `fevm_ps_dr_us_east_2_catalog`
  (`mig_source_sim` -> `mig_target`) because catalog creation on this workspace
  requires a managed location.
- S8 and S10 both surface as `upstream_drift`/genuine-data but differ in
  mechanism (stale snapshot vs never-populated source column).
