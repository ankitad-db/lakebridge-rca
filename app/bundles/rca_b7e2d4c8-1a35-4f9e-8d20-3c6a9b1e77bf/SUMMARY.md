# 🧭 RCA Summary — recon `b7e2d4c8-1a35-4f9e-8d20-3c6a9b1e77bf`

**12 findings** across **10 table pair(s)** · source dialect: `snowflake`

| Verdict | Count | Meaning |
| :-- | --: | :-- |
| 🔧 Migration-induced | 9 | Fix in the migration |
| 📊 Genuine data difference | 1 | Route to the data owner |
| 🔍 Needs review | 2 | Investigate further |
| ✅ Benign / expected | 0 | No action |

## 🔺 Top priorities

| Severity | Location | Verdict | Fix / next step |
| :-- | :-- | :-- | :-- |
| 🔴 High (98) | `edge_numeric.v_double` | 🔧 | Match the source numeric type/scale — keep DECIMAL(p,s); avoid casting to DOUBLE/INT. |
| 🔴 High (98) | `agg_weekly_sales.week_start` | 🔧 | Align session config (e.g., week-start day) between the source and Spark. |
| 🔴 High (98) | `dim_flag.active_flag` | 🔧 | Align null/boolean encoding with source (Y/N, 1/0, NULL vs ''/sentinel). |
| 🔴 High (98) | `edge_string.name_ws` | 🔧 | Preserve source casing and trim/normalize (whitespace, Unicode NFC) on load. |
| 🔴 High (80) | `edge_geo (schema)` | 🔧 | Reconcile the schema change: column rename + type widening + nullability. |

## 📋 Reconciliation overview (per table pair)

| Target table | Schema | ➖ Missing in target | ➕ Extra in target | 🔤 Mismatched columns | Verdicts |
| :-- | :-: | --: | --: | :-- | :-- |
| `agg_weekly_sales` | ✅ | · | · | 1 (`week_start`) | 🔧1 |
| `dim_config` | ✅ | · | · | 1 (`settings_json`) | 🔍1 |
| `dim_flag` | ✅ | · | · | 1 (`active_flag`) | 🔧1 |
| `dim_supplier` | ✅ | · | · | 1 (`contact_email`) | 📊1 |
| `edge_events` | ✅ | · | · | 1 (`event_ts`) | 🔍1 |
| `edge_geo` | ⚠️ 1 | · | · | 0 | 🔧1 |
| `edge_numeric` | ✅ | · | · | 2 (`v_double`, `big_id`) | 🔧2 |
| `edge_string` | ✅ | · | · | 2 (`name_ws`, `name_unicode`) | 🔧2 |
| `fact_inventory` | ✅ | · | · | 1 (`reorder_level`) | 🔧1 |
| `fact_payments` | ✅ | · | 10 | 0 | 🔧1 |

## 📈 Match rates (row & column level)

Reconciliation health per table pair. **Row match %** = source rows that exist in target *and* match on all columns.

| Target table | Source rows | Target rows | ➖ Missing | ➕ Extra | Mismatched rows | ✅ Row match % |
| :-- | --: | --: | --: | --: | --: | --: |
| `edge_numeric` | 5,000 | 5,000 | 0 | 0 | 5,000 | **0.00%** |
| `agg_weekly_sales` | 104 | 104 | 0 | 0 | 104 | **0.00%** |
| `dim_flag` | 100 | 100 | 0 | 0 | 100 | **0.00%** |
| `edge_string` | 1,500 | 1,500 | 0 | 0 | 1,500 | **0.00%** |
| `edge_events` | 10,000 | 10,000 | 0 | 0 | 2,500 | **75.00%** |
| `dim_config` | 20 | 20 | 0 | 0 | 3 | **85.00%** |
| `dim_supplier` | 300 | 300 | 0 | 0 | 5 | **98.33%** |
| `fact_inventory` | 4,000 | 4,000 | 0 | 0 | 60 | **98.50%** |
| `edge_geo` | 800 | 800 | 0 | 0 | 0 | **100.00%** |
| `fact_payments` | 5,990 | 6,000 | 0 | 10 | 0 | **100.00%** |

**Column-level match %** _(columns not listed matched 100%)_:

| Table.Column | Rows | Mismatches | ✅ Match % |
| :-- | --: | --: | --: |
| `edge_numeric.v_double` | 5,000 | 5,000 | 0.00% |
| `agg_weekly_sales.week_start` | 104 | 104 | 0.00% |
| `dim_flag.active_flag` | 100 | 100 | 0.00% |
| `edge_string.name_ws` | 1,500 | 1,500 | 0.00% |
| `edge_events.event_ts` | 10,000 | 2,500 | 75.00% |
| `dim_config.settings_json` | 20 | 3 | 85.00% |
| `edge_string.name_unicode` | 1,500 | 200 | 86.67% |
| `dim_supplier.contact_email` | 300 | 5 | 98.33% |
| `fact_inventory.reorder_level` | 4,000 | 60 | 98.50% |
| `edge_numeric.big_id` | 5,000 | 3 | 99.94% |


## 🎯 Findings by verdict _(highest impact first)_

## 🔧 Migration-induced — _Fix in the migration_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `edge_numeric.v_double` | 🔴 High | 🔢 type_precision | 92% | · | source DECIMAL(18,6) migrated to DOUBLE -> binary float representation error |
| `agg_weekly_sales.week_start` | 🔴 High | ⚙️ env_config | 92% | · | week-start config differs (Monday vs Sunday) between source and Spark |
| `dim_flag.active_flag` | 🔴 High | ␀ null_boolean | 92% | · | 1/0 integer flag -> true/false boolean |
| `edge_string.name_ws` | 🔴 High | 🔤 string_format | 92% | · | trailing whitespace only |
| `edge_geo (schema)` | 🔴 High | 🔢 type_precision | 92% | · | column renamed + type widened (DECIMAL(9,6)->DOUBLE) + nullability change |
| `fact_payments (extra rows)` | 🔴 High | ➕ volume_extra | 92% | ✓ | non-idempotent merge re-ran -> duplicate payment rows in target |
| `edge_string.name_unicode` | 🟠 Medium | 🔤 string_format | 92% | · | Unicode NFC vs NFD normalization (visually identical; normalize on load) |
| `edge_numeric.big_id` | 🟠 Medium | 🔢 type_precision | 92% | · | source NUMBER(38,0) cast to INT -> integer overflow / wrap |
| `fact_inventory.reorder_level` | 🟠 Medium | ␀ null_boolean | 92% | · | NULL replaced by sentinel -1 in target |

## 📊 Genuine data difference — _Route to the data owner_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `dim_supplier.contact_email` | 🟢 Low | 🌊 upstream_drift | 82% | · | target NULL where source populated (dropped/late upstream) -> route to data owner |

## 🔍 Needs review — _Investigate further_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `edge_events.event_ts` | 🟠 Medium | 🕐 timezone | 58% | · | offset varies by row (not constant) -> cannot be a single tz normalization; needs review |
| `dim_config.settings_json` | 🟠 Medium | 🧬 semi_structured | 58% | · | JSON value genuinely different (not a reorder) -> not benign |

---

# 🧾 Conclusion & recommended actions

Analyzed **12 findings**. Every verdict below is backed by a query executed in this notebook (see the cell under each finding).

## 🔧 Fix in the migration — 9 (owner: migration engineer)
- `edge_numeric.v_double` — Match the source numeric type/scale — keep DECIMAL(p,s); avoid casting to DOUBLE/INT.
- `agg_weekly_sales.week_start` — Align session config (e.g., week-start day) between the source and Spark.
- `dim_flag.active_flag` — Align null/boolean encoding with source (Y/N, 1/0, NULL vs ''/sentinel).
- `edge_string.name_ws` — Preserve source casing and trim/normalize (whitespace, Unicode NFC) on load.
- `edge_geo (schema)` — Reconcile the schema change: column rename + type widening + nullability.
- `fact_payments (extra rows)` — Make the merge idempotent; dedupe on the natural key to remove fan-out duplicates.
- `edge_string.name_unicode` — Preserve source casing and trim/normalize (whitespace, Unicode NFC) on load.
- `edge_numeric.big_id` — Match the source numeric type/scale — keep DECIMAL(p,s); avoid casting to DOUBLE/INT.
- `fact_inventory.reorder_level` — Align null/boolean encoding with source (Y/N, 1/0, NULL vs ''/sentinel).

## 📊 Route to the data owner — 1 (not migration bugs)
- `dim_supplier.contact_email` — Route to the data owner — a real source/upstream difference, not a migration bug.

## 🔍 Needs review — 2
- `edge_events.event_ts` — Offset varies per row — inspect source timezone handling before applying a single fix.
- `dim_config.settings_json` — Values genuinely differ (not a reorder) — confirm the intended value with the data owner.

## ✅ Benign / expected — 0
- 0 finding(s) are representation-only or within tolerance; no action.

> If re-running a cell changes an output, update that finding's verdict above and regenerate this report so the conclusion always matches the evidence.