# ReconResolve — Retail "Sales & Revenue" demo runbook

Two leadership-demo use cases on a real Snowflake→Databricks retail migration, reconciled by
**genuine Lakebridge `reconcile`** on workspace `ps-dr-east` and root-caused by ReconResolve,
run end-to-end **through the `rca-recon` skill** (the Genie Code path — not the CLI):

| Bed | recon_id | Mode | What it shows |
|---|---|---|---|
| **Hybrid** | `218dab3c4c51443783dbf14a16c324fc` | Deterministic **+ agentic** | Tier-1 rules resolve the clean defects; the Tier-2 FM (`databricks-claude-opus-5`) precisely root-causes the hard ones, each **proven by a live query** |
| **Deterministic** | `eca72dd859f246088271a0ac0e43ddae` | **Deterministic only** | Every verdict from rule-based probes + one confirming query — no LLM |
| Aggregate | `d90e15507e02494190c6d87cd59123bf` | Deterministic | `aggregates-reconcile` per-rule RCA (SUM/AVG by group) |

The two beds share the **same rich, composed ETL** (`migration/retail_demo/*_target.sql`) — the
only difference is which *kind* of defect is seeded, so the contrast is purely deterministic-vs-agentic.

---

## The migration (what's being reconciled)

A retail Sales & Revenue mart migrated from a Snowflake EDW to Unity Catalog. Source =
correct EDW gold (ground truth); target = the migrated Databricks ETL, which reads the landed
raw extract and rebuilds the star schema with **realistic, composed transforms**:

```sql
net_revenue  = ROUND(quantity * unit_price * (1 - discount_pct) * (1 + tax_rate), 4)   -- multiplicative
amount_usd   = ROUND(quantity * unit_price * fx.rate_to_usd, 2)                        -- FX join (dim_fx, daily)
status_bucket= CASE status_code WHEN 'A'..'C'..'P'..'R'.. END                          -- multi-branch mapping
customer_name= INITCAP(TRIM(customer_name_raw))    order_ts_utc = order_ts (canonical)  unit_price DECIMAL(18,4)
```

### Seeded defects

**Hybrid bed** (`mig_hyb_*`) — 4 deterministic + 3 agentic:

| Column | Injected defect | Tier | RCA verdict |
|---|---|---|---|
| `unit_price` | `ROUND(...,2)` — scale loss | deterministic | 🔢 type_precision · 98% |
| `customer_name` | `UPPER(TRIM())` vs proper case | deterministic | 🔤 string_format · 98% |
| `order_ts_utc` | `+ INTERVAL 5 HOURS` | deterministic | 🕐 timezone (5.0h) · 98% |
| (rows) | `WHERE order_id % 500 <> 0` | deterministic | ➖ volume_missing (4,000) |
| **`net_revenue`** | discount & tax applied **additively** — the `(1-d)(1+t)` cross-term `+d·t` is dropped | **agentic** | 🔀 transpilation · **95% · ✓ query-confirmed** |
| **`amount_usd`** | FX joined at **month-start** grain instead of the daily rate | **agentic** | 🔀 transpilation · **95% · ✓ query-confirmed** |
| **`status_bucket`** | the `'R'` (Returned) `CASE` branch dropped → `ELSE 'Unknown'` | **agentic** | 🔀 transpilation · **95% · ✓ query-confirmed** |

The three agentic findings are exactly the cases a rule can't name: the FM reconstructs the
migrated derivation from the artifact, proposes the mechanism, and a **live confirming query
promotes it only if it matches every row**. Sample confirmed root causes:

- `net_revenue` → *"applies tax to the undiscounted gross and subtracts the raw discount instead
  of taxing the discounted net — inflates net_revenue by qty·price·discount·tax."*
- `amount_usd` → *"joins `dim_fx` at month-start (`fx_date = TRUNC(order_dt,'MM')`) instead of the
  daily FX date, so intra-month rate drift is lost."*
- `status_bucket` → *"the migrated `CASE` has no branch for `'R'`, so `Returned` rows collapse into
  `ELSE 'Unknown'`."*

**Deterministic bed** (`mig_det_*`) — every defect cleanly rule-resolvable:
`unit_price`/`net_revenue`/`list_price` precision + schema type, `customer_name`/`email`/`product_name`
string-format, `is_active` `'Y'/'N'`→`'true'/'false'` boolean, `order_ts_utc` timezone,
`tax_rate` within a declared ±0.01 threshold (benign — correctly **not** flagged), volume_missing
(load filter) + volume_extra (a re-loaded shard), and the `aggregates-reconcile` SUM/AVG-by-group.

---

## Run it from the workspace (Genie Code / skill)

The skill is deployed at `/Workspace/Users/<you>/.assistant/skills/rca-recon`. In **Genie Code
(Agent mode)** just state the intent — the agent invokes the skill:

> "Root-cause the reconciliation `218dab3c4c51443783dbf14a16c324fc`."

To run headless (as this demo did), the driver notebook `rca_skill_driver` calls the skill's
`run()` with the workspace Spark session:

```python
run_rca.run(recon_id, spark,
            llm_endpoint="databricks-claude-opus-5",   # hybrid bed; omit for the deterministic bed
            transpiled_output_dir=".../demo_artifacts/hybrid")  # the migrated-SQL artifact
```

Each run writes a self-contained bundle to `/Workspace/Users/<you>/rca_notebooks/rca_<recon_id>/`:
`00_index.ipynb`, one notebook per table, `SUMMARY.md`, and `rca_<recon_id>.json`.

---

## What to show leadership

1. **Open `fact_sales.ipynb` in the hybrid bundle.** Each column finding leads with a
   **`🔧 Transformation logic`** callout — the exact migrated derivation — then the verdict,
   confidence, and a re-runnable confirming query.
2. **Contrast the two beds.** Deterministic bed: every verdict is a rule + one query, no LLM.
   Hybrid bed: the same report, plus three findings the FM root-caused precisely — and each is
   backed by a query the reviewer can re-run. **Verdicts are never a bare model guess.**
3. **The `net_revenue` story.** A rule would say "values differ / rounding." The agentic tier
   says *which term of the formula is wrong* and proves it — the depth a migration engineer needs.
4. **Threshold discipline.** `tax_rate` differs but sits inside the declared tolerance, so it is
   reported benign, not raised as a defect — no false alarms.
5. **Aggregate RCA.** `SUM(net_revenue) BY is_active` doesn't reconcile because the `is_active`
   boolean mapping changed the group keys — the tool names that, not just "totals differ."

Rebuild everything from scratch: `migration/retail_demo/build_retail_beds.py` →
`reconcile_retail.py` → `rca_skill_driver`. Benchmarks: `docs/BENCHMARKS.md`.
