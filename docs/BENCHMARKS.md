# ReconResolve — Benchmarks

Correctness, latency, stress, and data size for the two retail demo beds, measured on
**genuine Lakebridge reconcile output** (Snowflake→Databricks retail mart on `ps-dr-east`,
2,000,000-row `fact_sales` + dims), run **through the `rca-recon` skill** (workspace Spark).
Ground truth = the known seeded defects (`migration/retail_demo/*_target.sql`).

recon_ids: hybrid `218dab3c4c51443783dbf14a16c324fc` · deterministic `eca72dd859f246088271a0ac0e43ddae`
· aggregate `d90e15507e02494190c6d87cd59123bf`.

---

## 1. Correctness / quality

### Hybrid bed — deterministic + agentic (7 seeded fact defects + dims)

| Seeded defect | Column | Tier | RCA category / verdict | Conf. | Query-confirmed |
|---|---|---|---|---|---|
| Scale loss `ROUND(,2)` | `unit_price` | deterministic | 🔢 type_precision · migration-induced | 98% | ✓ |
| Case/whitespace | `customer_name` | deterministic | 🔤 string_format · migration-induced | 98% | ✓ |
| Timezone `+5h` | `order_ts_utc` | deterministic | 🕐 timezone (5.0h) · migration-induced | 98% | ✓ |
| Dropped rows (load filter) | (rows) | deterministic | ➖ volume_missing (4,000) | 95% | ✓ |
| **Missing `(1-d)(1+t)` cross-term** | **`net_revenue`** | **agentic** | 🔀 transpilation · migration-induced | **95%** | **✓** |
| **FX joined at month-start grain** | **`amount_usd`** | **agentic** | 🔀 transpilation · migration-induced | **95%** | **✓** |
| **Dropped `'R'` CASE branch** | **`status_bucket`** | **agentic** | 🔀 transpilation · migration-induced | **95%** | **✓** |

**Detection 7/7 · category 7/7 · verdict 7/7 · query-confirmed 7/7.** The three agentic
findings are the ones no rule can name; each was promoted **only after a live reconstruction
query matched every row**. (`amount_usd` is nailed because the evidence bundle now carries the
FROM/JOIN + `dim_fx`'s real columns, so the model reconstructs the join instead of guessing.)

### Deterministic bed — Tier-1 only (13 findings, no LLM)

| Defect | Columns | Category | Conf. |
|---|---|---|---|
| Precision / scale + schema type | `unit_price`, `net_revenue`, `list_price` | 🔢 type_precision | 98% / 70% (schema) |
| Case/format | `customer_name`, `email`, `product_name` | 🔤 string_format | 98% |
| Boolean mapping `'Y'/'N'`→`'true'/'false'` | `is_active` (fact + dim) | ␀ null_boolean | 98% |
| Timezone `+5h` | `order_ts_utc` | 🕐 timezone | 98% |
| Dropped rows | (rows) | ➖ volume_missing | 95% |
| **Within tolerance** | `tax_rate` (±0.01) | — **correctly not flagged (benign)** | — |

Every verdict from a rule + one confirming query; `llm_fallback` was **not** invoked (no
endpoint). `tax_rate` sits inside the declared threshold and is suppressed — **no false alarm**.

### Aggregate bed — `aggregates-reconcile`

`SUM(net_revenue) BY is_active` and `AVG(net_revenue) BY is_active` both flagged: the
`is_active` boolean mapping changed the group-by **keys** (`'Y'/'N'` vs `'true'/'false'`), so
groups don't align — root-caused as a grouping-key transform, confirmed by recomputing the
aggregate on both sides.

---

## 2. Latency (real, from the runs)

Reconcile = Lakebridge job (job cluster). RCA = skill compute on workspace Spark, measured from
the `rca_genie_audit` table (`duration_ms`), excluding serverless start / `%pip` overhead.

| Stage | Hybrid | Deterministic | Aggregate |
|---|--:|--:|--:|
| Lakebridge `reconcile` (2M×3 tables, `report_type=all`) | 5,349 s cold¹ | 944 s warm¹ | — |
| **RCA — skill, full enrichment** (drill-down + drift + UC lineage + blast radius + fix-validation) | — | **~270 s** | **~18 s** |
| **RCA — skill, + agentic Tier-2** (adds FM reconstruct/confirm per residual) | **~290–400 s** | — | — |

¹ Reconcile wall-time is dominated by **job-cluster spin** (the first, cold run was ~89 min
incl. spin; a warm cluster reconciled the same shape in ~16 min). The RCA cost is driven by the
optional **live enrichments** (each does a bounded Spark scan) and, for hybrid, the **FM calls**
(one reconstruct+confirm round-trip per residual) — every enrichment is individually toggleable,
so a lean deterministic pass (`--no-drilldown`, lineage off) runs in seconds.

---

## 3. Stress — fleet of concurrent RCA jobs

Nine RCA skill runs submitted **at once** (the three retail recon_ids ×2 each + three historical
recons):

- **6 / 6 retail runs SUCCEEDED under concurrent load, ~500 s wall-clock** (vs the sum of their
  serial compute ~1,900 s) — the pipeline parallelizes cleanly across a fleet.
- The 3 historical recons errored **only because their source/target tables were dropped** after
  earlier demos (the RCA degrades on missing tables rather than corrupting output) — not a
  pipeline limit.
- No cross-run interference: audit rows, notebook bundles, and verdicts were correct for every
  concurrent run.

---

## 4. Data size

Stored (Delta/Parquet, `DESCRIBE DETAIL sizeInBytes`) for the reconciled `fact_sales` pairs:

| Table | Rows | Stored |
|---|--:|--:|
| `mig_hyb_src.fact_sales` | 2,000,000 | 8.5 MB |
| `mig_hyb_tgt.fact_sales` | 1,996,000 | 7.4 MB |
| `mig_det_src.fact_sales` | 2,000,000 | 8.5 MB |
| `mig_det_tgt.fact_sales` | 1,998,002 | 11.3 MB |
| **fact_sales total (4)** | **~8 M** | **~35.7 MB** |

Plus `dim_customer` (20k), `dim_product` (2k), `dim_fx` (3,655 daily rates). The demo columns are
low-cardinality, so Parquet compresses ~20–30× — the **logical/uncompressed** footprint is ~0.15 GB
per fact table (~0.6 GB across the four). A true multi-hundred-GB / **TB** benchmark needs wider,
higher-cardinality rows: raise `N` in `build_retail_beds.py` and widen the row — flagged as a
follow-up (larger data-gen + warehouse cost), reproducible from the same scripts.

---

## 5. Takeaways for leadership

- **Explains every reconcile difference with the right root cause, query-backed** — the
  deterministic tier concludes with a re-runnable query; the agentic tier adds *precision* on the
  hard ones (which formula term, which join grain, which CASE branch) and is **promoted only when a
  query confirms** — never a bare model guess.
- **Two modes, one flag.** Deterministic-only for auditable, no-LLM runs; deterministic+agentic
  when you want the long tail root-caused. Same engine, same report.
- **Handles a fleet.** Six concurrent 2M-row RCA runs in ~500 s wall, every verdict correct.
- **Honest.** Within-tolerance diffs are suppressed; dropped-table recons degrade gracefully;
  aggregate mismatches are root-caused, not just counted.

Reproduce: `migration/retail_demo/build_retail_beds.py` → `reconcile_retail.py` →
`rca_skill_driver` (per `docs/retail_demo_runbook.md`); stress via `stress_rca.py`.
