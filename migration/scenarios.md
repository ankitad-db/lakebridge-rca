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
