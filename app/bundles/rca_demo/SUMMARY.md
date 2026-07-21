# 🧭 RCA Summary — recon `demo`

**8 findings** across **6 table pair(s)** · source dialect: `snowflake`

| Verdict | Count | Meaning |
| :-- | --: | :-- |
| 🔧 Migration-induced | 5 | Fix in the migration |
| 📊 Genuine data difference | 1 | Route to the data owner |
| 🔍 Needs review | 1 | Investigate further |
| ✅ Benign / expected | 1 | No action |

## 🔺 Top priorities

| Severity | Location | Verdict | Fix / next step |
| :-- | :-- | :-- | :-- |
| 🔴 High (98) | `fact_orders.order_ts` | 🔧 | Normalize ORDER_TS to UTC (convert_timezone) during the load. |
| 🔴 High (96) | `dim_product.sku` | 🔧 | Preserve source casing; trim trailing spaces. |
| 🔴 High (89) | `fact_order_items.amount` | 🔧 | Migrate AMOUNT as DECIMAL(18,4) to preserve source scale. |
| 🔴 High (80) | `fact_orders (missing rows)` | 🔧 | Remove/adjust the WHERE order_id<=480 watermark in the load. |
| 🟠 Medium (65) | `agg_daily_sales.revenue` | 🔧 | Match the source aggregation (no ROUND, or half-up to scale 2). |

## 📋 Reconciliation overview (per table pair)

| Target table | Schema | ➖ Missing in target | ➕ Extra in target | 🔤 Mismatched columns | Verdicts |
| :-- | :-: | --: | --: | :-- | :-- |
| `agg_daily_sales` | ✅ | · | · | 1 (`revenue`) | 🔧1 |
| `dim_customer` | ✅ | · | · | 2 (`loyalty_tier`, `attributes`) | 📊1 ✅1 |
| `dim_product` | ✅ | · | · | 1 (`sku`) | 🔧1 |
| `fact_order_items` | ✅ | · | · | 1 (`amount`) | 🔧1 |
| `fact_orders` | ✅ | 20 | · | 1 (`order_ts`) | 🔧2 |
| `fact_payments` | ✅ | · | 10 | 0 | 🔍1 |

## 📈 Match rates (row & column level)

Reconciliation health per table pair. **Row match %** = source rows that exist in target *and* match on all columns.

| Target table | Source rows | Target rows | ➖ Missing | ➕ Extra | Mismatched rows | ✅ Row match % |
| :-- | --: | --: | --: | --: | --: | --: |
| `fact_orders` | 500 | 480 | 20 | 0 | 480 | **0.00%** |
| `dim_product` | 30 | 30 | 0 | 0 | 30 | **0.00%** |
| `dim_customer` | 100 | 100 | 0 | 0 | 100 | **0.00%** |
| `fact_order_items` | 1,500 | 1,510 | 0 | 0 | 1,180 | **21.33%** |
| `agg_daily_sales` | 150 | 150 | 0 | 0 | 42 | **72.00%** |
| `fact_payments` | 50 | 60 | 0 | 10 | 0 | **100.00%** |
| `dim_store` | 5 | 5 | 0 | 0 | 0 | **100.00%** |

**Column-level match %** _(columns not listed matched 100%)_:

| Table.Column | Rows | Mismatches | ✅ Match % |
| :-- | --: | --: | --: |
| `fact_orders.order_ts` | 480 | 480 | 0.00% |
| `dim_product.sku` | 30 | 30 | 0.00% |
| `dim_customer.loyalty_tier` | 100 | 100 | 0.00% |
| `dim_customer.attributes` | 100 | 100 | 0.00% |
| `fact_order_items.amount` | 1,500 | 1,180 | 21.33% |
| `agg_daily_sales.revenue` | 150 | 42 | 72.00% |


## 🎯 Findings by verdict _(highest impact first)_

## 🔧 Migration-induced — _Fix in the migration_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `fact_orders.order_ts` | 🔴 High | 🕐 timezone | 93% | ✓ | Constant +5:30 offset on every row; TIMESTAMP_LTZ not normalized to UTC on load. |
| `dim_product.sku` | 🔴 High | 🔤 string_format | 85% | · | SKU lower-cased with trailing whitespace during the transform. |
| `fact_order_items.amount` | 🔴 High | 🔢 type_precision | 96% | ✓ | Target AMOUNT is DECIMAL(18,2) vs source DECIMAL(18,4); scale-4 digits are lost. |
| `fact_orders (missing rows)` | 🔴 High | ➖ volume_missing | 90% | ✓ | 20 source rows (order_id>480) never landed; a load watermark drops late rows. |
| `agg_daily_sales.revenue` | 🟠 Medium | 🔀 transpilation | 88% | · | REVENUE rounded to whole units vs source exact SUM; ROUND rounding-mode diff. |

## 📊 Genuine data difference — _Route to the data owner_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `dim_customer.loyalty_tier` | 🟠 Medium | 🌊 upstream_drift | 82% | ✓ | Source LOYALTY_TIER is NULL for all rows while target is populated — a genuine data/provenance difference, ... |

## 🔍 Needs review — _Investigate further_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `fact_payments (extra rows)` | 🟠 Medium | ➕ volume_extra | 60% | · | 10 extra target rows; likely a non-idempotent re-load fan-out. Confirm dedup. |

## ✅ Benign / expected — _No action_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `dim_customer.attributes` | 🟢 Low | 🧬 semi_structured | 90% | · | VARIANT re-serialized with keys reordered; payloads are semantically equal. |

---

# 🧾 Conclusion & recommended actions

Analyzed **8 findings**. Every verdict below is backed by a query executed in this notebook (see the cell under each finding).

## 🔧 Fix in the migration — 5 (owner: migration engineer)
- `fact_orders.order_ts` — Normalize ORDER_TS to UTC (convert_timezone) during the load.
- `dim_product.sku` — Preserve source casing; trim trailing spaces.
- `fact_order_items.amount` — Migrate AMOUNT as DECIMAL(18,4) to preserve source scale.
- `fact_orders (missing rows)` — Remove/adjust the WHERE order_id<=480 watermark in the load.
- `agg_daily_sales.revenue` — Match the source aggregation (no ROUND, or half-up to scale 2).

## 📊 Route to the data owner — 1 (not migration bugs)
- `dim_customer.loyalty_tier` — Route to the data owner: confirm whether target enrichment is intended.

## 🔍 Needs review — 1
- `fact_payments (extra rows)` — Make the merge idempotent; dedupe on the natural key.

## ✅ Benign / expected — 1
- 1 finding(s) are representation-only or within tolerance; no action.

> If re-running a cell changes an output, update that finding's verdict above and regenerate this report so the conclusion always matches the evidence.