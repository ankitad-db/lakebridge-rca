# 🧭 RCA Summary — recon `a3f9c1e2-7b64-4d0a-9c31-6f2b8e5d41aa`

**11 findings** across **5 table pair(s)** · source dialect: `snowflake`

| Verdict | Count | Meaning |
| :-- | --: | :-- |
| 🔧 Migration-induced | 8 | Fix in the migration |
| 📊 Genuine data difference | 1 | Route to the data owner |
| 🔍 Needs review | 1 | Investigate further |
| ✅ Benign / expected | 1 | No action |

## 🔺 Top priorities

| Severity | Location | Verdict | Fix / next step |
| :-- | :-- | :-- | :-- |
| 🔴 High (98) | `dim_customer.is_active` | 🔧 | Align null/boolean encoding with source (Y/N, 1/0, NULL vs ''/sentinel). |
| 🔴 High (98) | `dim_product.sku` | 🔧 | Preserve source casing and trim/normalize (whitespace, Unicode NFC) on load. |
| 🔴 High (96) | `fact_orders.order_ts` | 🔧 | Normalize timestamps to UTC on load (convert_timezone) so the constant offset disappears. |
| 🔴 High (80) | `fact_order_items.amount` | 🔧 | Match the source numeric type/scale — keep DECIMAL(p,s); avoid casting to DOUBLE/INT. |
| 🔴 High (80) | `fact_order_items (extra rows)` | 🔧 | Make the merge idempotent; dedupe on the natural key to remove fan-out duplicates. |

## 📋 Reconciliation overview (per table pair)

| Target table | Schema | ➖ Missing in target | ➕ Extra in target | 🔤 Mismatched columns | Verdicts |
| :-- | :-: | --: | --: | :-- | :-- |
| `agg_daily_sales` | ✅ | · | · | 1 (`revenue`) | 🔧1 |
| `dim_customer` | ✅ | · | · | 5 (`attributes`, `marketing_segment`, `is_active`, `email`, `loyalty_tier`) | 🔧2 📊1 🔍1 ✅1 |
| `dim_product` | ✅ | · | · | 1 (`sku`) | 🔧1 |
| `fact_order_items` | ✅ | · | 15 | 1 (`amount`) | 🔧2 |
| `fact_orders` | ✅ | 20 | · | 1 (`order_ts`) | 🔧2 |

## 📈 Match rates (row & column level)

Reconciliation health per table pair. **Row match %** = source rows that exist in target *and* match on all columns.

| Target table | Source rows | Target rows | ➖ Missing | ➕ Extra | Mismatched rows | ✅ Row match % |
| :-- | --: | --: | --: | --: | --: | --: |
| `fact_orders` | 500 | 480 | 20 | 0 | 480 | **0.00%** |
| `dim_customer` | 1,000 | 1,000 | 0 | 0 | 1,000 | **0.00%** |
| `dim_product` | 200 | 200 | 0 | 0 | 200 | **0.00%** |
| `fact_order_items` | 2,000 | 2,015 | 0 | 15 | 1,200 | **40.00%** |
| `agg_daily_sales` | 365 | 365 | 0 | 0 | 120 | **67.12%** |
| `dim_store` | 50 | 50 | 0 | 0 | 0 | **100.00%** |

**Column-level match %** _(columns not listed matched 100%)_:

| Table.Column | Rows | Mismatches | ✅ Match % |
| :-- | --: | --: | --: |
| `dim_customer.attributes` | 1,000 | 1,000 | 0.00% |
| `dim_customer.is_active` | 1,000 | 1,000 | 0.00% |
| `dim_customer.loyalty_tier` | 1,000 | 1,000 | 0.00% |
| `dim_product.sku` | 200 | 200 | 0.00% |
| `fact_orders.order_ts` | 500 | 480 | 4.00% |
| `fact_order_items.amount` | 2,000 | 1,200 | 40.00% |
| `agg_daily_sales.revenue` | 365 | 120 | 67.12% |
| `dim_customer.marketing_segment` | 1,000 | 40 | 96.00% |
| `dim_customer.email` | 1,000 | 30 | 97.00% |


## 🎯 Findings by verdict _(highest impact first)_

## 🔧 Migration-induced — _Fix in the migration_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `dim_customer.is_active` | 🔴 High | ␀ null_boolean | 92% | · | Y/N -> true/false boolean encoding |
| `dim_product.sku` | 🔴 High | 🔤 string_format | 92% | · | target lower-cased + trailing whitespace |
| `fact_orders.order_ts` | 🔴 High | 🕐 timezone | 92% | · | target = source + 5:30, no UTC normalization (TIMESTAMP_LTZ) |
| `fact_order_items.amount` | 🔴 High | 🔢 type_precision | 92% | · | source DECIMAL(18,4) migrated as DECIMAL(18,2) -> scale loss |
| `fact_order_items (extra rows)` | 🔴 High | ➕ volume_extra | 92% | ✓ | fan-out duplicates for order_id <= 5 (15 extra rows) |
| `fact_orders (missing rows)` | 🔴 High | ➖ volume_missing | 92% | ✓ | watermark drops order_id > 480 (20 late rows) |
| `agg_daily_sales.revenue` | 🔴 High | 🔀 transpilation | 92% | · | ROUND(sum,0) vs source DECIMAL(18,2) sum (rounding-mode diff) |
| `dim_customer.email` | 🟠 Medium | ␀ null_boolean | 92% | · | NULL email -> empty string |

## 📊 Genuine data difference — _Route to the data owner_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `dim_customer.marketing_segment` | 🟢 Low | 🌊 upstream_drift | 82% | · | source updated after extract; target holds STALE for every 25th customer |

## 🔍 Needs review — _Investigate further_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `dim_customer.loyalty_tier` | 🟠 Medium | 🌊 upstream_drift | 58% | · | source NULL (never populated); target fabricated -> generated column, needs human decision |

## ✅ Benign / expected — _No action_

| Location | Severity | Category | Conf. | ✔ | Root cause |
| :-- | :-- | :-- | :-: | :-: | :-- |
| `dim_customer.attributes` | 🟢 Low | 🧬 semi_structured | 90% | · | JSON keys reordered; semantically equal |

---

# 🧾 Conclusion & recommended actions

Analyzed **11 findings**. Every verdict below is backed by a query executed in this notebook (see the cell under each finding).

## 🔧 Fix in the migration — 8 (owner: migration engineer)
- `dim_customer.is_active` — Align null/boolean encoding with source (Y/N, 1/0, NULL vs ''/sentinel).
- `dim_product.sku` — Preserve source casing and trim/normalize (whitespace, Unicode NFC) on load.
- `fact_orders.order_ts` — Normalize timestamps to UTC on load (convert_timezone) so the constant offset disappears.
- `fact_order_items.amount` — Match the source numeric type/scale — keep DECIMAL(p,s); avoid casting to DOUBLE/INT.
- `fact_order_items (extra rows)` — Make the merge idempotent; dedupe on the natural key to remove fan-out duplicates.
- `fact_orders (missing rows)` — Remove/adjust the load filter (watermark) that drops late source rows.
- `agg_daily_sales.revenue` — Match the source aggregation/rounding semantics (avoid ROUND rounding-mode drift).
- `dim_customer.email` — Align null/boolean encoding with source (Y/N, 1/0, NULL vs ''/sentinel).

## 📊 Route to the data owner — 1 (not migration bugs)
- `dim_customer.marketing_segment` — Route to the data owner — a real source/upstream difference, not a migration bug.

## 🔍 Needs review — 1
- `dim_customer.loyalty_tier` — Human decision required: confirm whether the target-only values are intended.

## ✅ Benign / expected — 1
- 1 finding(s) are representation-only or within tolerance; no action.

> If re-running a cell changes an output, update that finding's verdict above and regenerate this report so the conclusion always matches the evidence.