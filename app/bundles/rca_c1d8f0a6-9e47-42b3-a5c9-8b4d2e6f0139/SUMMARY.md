# 🧭 RCA Summary — recon `c1d8f0a6-9e47-42b3-a5c9-8b4d2e6f0139`

**0 findings** across **0 table pair(s)** · source dialect: `snowflake`

| Verdict | Count | Meaning |
| :-- | --: | :-- |
| 🔧 Migration-induced | 0 | Fix in the migration |
| 📊 Genuine data difference | 0 | Route to the data owner |
| 🔍 Needs review | 0 | Investigate further |
| ✅ Benign / expected | 0 | No action |

## 📋 Reconciliation overview (per table pair)

| Target table | Schema | ➖ Missing in target | ➕ Extra in target | 🔤 Mismatched columns | Verdicts |
| :-- | :-: | --: | --: | :-- | :-- |

## 📈 Match rates (row & column level)

Reconciliation health per table pair. **Row match %** = source rows that exist in target *and* match on all columns.

| Target table | Source rows | Target rows | ➖ Missing | ➕ Extra | Mismatched rows | ✅ Row match % |
| :-- | --: | --: | --: | --: | --: | --: |
| `fact_order_items` | 2,000 | 2,000 | 0 | 0 | 0 | **100.00%** |
| `fact_orders` | 500 | 500 | 0 | 0 | 0 | **100.00%** |
| `dim_customer` | 1,000 | 1,000 | 0 | 0 | 0 | **100.00%** |
| `dim_product` | 200 | 200 | 0 | 0 | 0 | **100.00%** |
| `agg_daily_sales` | 365 | 365 | 0 | 0 | 0 | **100.00%** |
| `dim_store` | 50 | 50 | 0 | 0 | 0 | **100.00%** |


## 🎯 Findings by verdict _(highest impact first)_

---

# 🧾 Conclusion & recommended actions

Analyzed **0 findings**. Every verdict below is backed by a query executed in this notebook (see the cell under each finding).

## 🔧 Fix in the migration — 0 (owner: migration engineer)
- _None._

## 📊 Route to the data owner — 0 (not migration bugs)
- _None._

## ✅ Benign / expected — 0
- 0 finding(s) are representation-only or within tolerance; no action.

> If re-running a cell changes an output, update that finding's verdict above and regenerate this report so the conclusion always matches the evidence.