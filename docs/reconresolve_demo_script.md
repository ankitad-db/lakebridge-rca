# ReconResolve — Demo Narration Script

**Format:** ~4 minutes. Each section = **Say** (speak) + **Show** (click). Demo recon:
`446d22cd1d2b40d7a4f6efdf1fdc3bdc` (retail Sales & Revenue mart, Snowflake → Databricks, **Deterministic**).

---

## 0 · The scenario (15s)
**Say:** "We migrated our retail *Sales & Revenue* mart from Snowflake to Databricks with Lakebridge. Reconcile flags differences across the tables. Every migration hits the same question — *which differences are migration bugs, which are real data, and how do we fix them?* That's ReconResolve."
**Show:** the app landing / Overview.

---

## 1 · Entry point (20s)
**Say:** "ReconResolve starts where Lakebridge reconcile ends. Its **input is the reconcile output** — a `recon_id`. We don't re-reconcile; we **leverage what Lakebridge already produced** and root-cause it."
**Say:** "Two modes:
- **Deterministic** — rules + one live confirming query per finding. No LLM. Fully auditable. *This demo runs deterministic — every finding is proven by a query.*
- **Hybrid** — adds a query-gated Foundation-Model tier for the hard, hand-tweaked transforms. The model proposes; a query confirms; a guess never sticks."
**Show:** Overview → the "How you'll use it" strip.

---

## 2 · Migration Health — the leadership view (25s)
**Say:** "First, the migration-wide picture. **KPIs** — recons run, tables, findings, and *actionable* work. The **verdict mix** — migration-induced vs genuine-data vs expected vs needs-review. And the **top recurring root causes** — timezone, precision, string-format, null/boolean."
**Say:** "One glance answers *how healthy is the migration, and where's the work.*"
**Show:** **Migration Health** tab — stat tiles, verdict-mix bar, top causes, RCA-mode column.

---

## 3 · Recon runs — pick a recon, run RCA (15s)
**Say:** "Recon runs lists every Lakebridge `recon_id`. Pick one, choose **Deterministic or Hybrid**, and run RCA. Here's our retail recon — Deterministic."
**Show:** **Recon runs** → 446d22 → open its dashboard.

---

## 4 · Run dashboard — where the differences are (25s)
**Say:** "The recon dashboard. **Rows matched** = records present on both sides; **Columns changed** = the fields whose values the migration altered."
**Say:** "`fact_sales` — 500,000 orders, **99.8% present** (~1,000 dropped by a stray load filter), with two columns changed: `order_ts_utc` and `unit_price`. `dim_customer` has one changed field. So two kinds of problem at a glance — some rows missing, and the rows that *are* there have wrong values. Not everything is broken — the tool points at exactly what is."
**Show:** the run dashboard table → the `fact_sales` row.

---

## 5 · The finding — issue, logic, script, fix (40s)  ← the money moment
**Say:** "Open `fact_sales` → `order_ts_utc`."
**Say (the issue, plain English):** "Every order's timestamp is exactly **5 hours late**. The migration 'normalised to UTC' by adding a flat +5 hours, but the source was already the canonical time. So an 8 p.m. order now lands after midnight — on the *next day* — and every daily sales-by-day and revenue-by-day report is shifted."
**Say (the proof):** "Under it: a **column-lineage flow** (source `order_ts` → the migrated transform → the target column), the exact **🔧 transformation logic** (`r.order_ts + INTERVAL 5 HOURS`), the **📄 script + line** where it's wrong, the **🔗 UC lineage**, and the **✔ confirming query** — it found a **single, constant 5-hour offset across every order present**. Deterministic, no AI — proven by a query."
**Say (the verdict):** "**Migration-induced, 98% confidence**, query-confirmed, with the **fix** and the **owner**."
**Show:** expand `order_ts_utc` → walk the evidence blocks top to bottom.

---

### 🔎 Deep-dive detail: `fact_sales.order_ts_utc` (say this in your own words)

**The issue — what's wrong:** the migration re-timestamped every order to "UTC" by adding a **fixed +5 hours**, but the Snowflake source was already stored in the canonical local time. So every order is shifted 5 hours forward.

- **Correct (Snowflake source):** `order_ts_utc = order_ts`  *(already canonical)*
- **Migrated (Databricks target, `revenue_target.sql:32`):** `order_ts_utc = r.order_ts + INTERVAL 5 HOURS`
- **Why it matters:** a fixed offset is not a timezone conversion. Orders near the end of the day roll onto the **next calendar day**, so any report that groups by day — daily sales, daily revenue, day-over-day trends — is wrong, even though the row counts and totals reconcile.

**How ReconResolve proved it (not a guess):** the deterministic drill-down ran a confirming query and found a **single distinct offset of exactly 5.00 hours across every order present** — the signature of a constant shift, not a genuine timezone/DST conversion. Verdict promoted to **migration-induced, 98% confidence, query-confirmed**.

**Where:** `revenue_target.sql`, line 32 · UC lineage: derives from source `mig_rev_src._raw.order_ts`.

**The resolution — fix:** drop the fixed +5h. If the times were genuinely local and need UTC, use a real timezone conversion, then re-run reconcile:
```sql
-- revenue_target.sql:32 — corrected order_ts_utc
r.order_ts AS order_ts_utc
-- or, if a real conversion is intended (e.g. US/Eastern → UTC):
convert_timezone('America/New_York', 'UTC', r.order_ts) AS order_ts_utc
```
Re-run Lakebridge reconcile on `fact_sales` → the `order_ts_utc` difference clears. **Owner:** migration engineer.

**Supporting findings (same recon, same clean treatment):**
- `fact_sales` — **~1,000 orders missing** (`WHERE order_id % 500 <> 0`): a stray **load filter** dropped rows on migration. Fix: remove the filter / back-fill. (This is why Rows matched shows 99.8%.)
- `fact_sales.unit_price` — landed as `DECIMAL(18,2)` vs the source `DECIMAL(18,4)`: a **precision / scale loss** on ~92% of rows. Fix: preserve the source scale.
- `dim_customer.customer_name` — `UPPER(TRIM(...))` on load vs the source's proper case: a **string-format (case)** difference. Fix: align case/collation in the transform.

---

## 6 · Close (15s)
**Say:** "Every reconcile difference — root-caused, query-backed, with a fix and an owner. Deterministic where rules suffice; AI only for the long tail; never a bare guess. And it's all audited."
**Say:** "**Lakebridge reconciles. ReconResolve resolves.**"
**Show:** Audit trail (who / when / tool), then back to Migration Health.

---

### Backup talking points (if asked)
- **"Is this AI?"** — Not for this recon. Every finding here is deterministic: a rule fires, then a confirming query proves it. Hybrid mode adds a Foundation-Model tier only for the hard, hand-tweaked transforms — and even then the model proposes a cause + a query, and the verdict sticks only if the query confirms. Worst case → needs-review, never a wrong answer.
- **"Does it scale?"** — RCA runs on the bounded recon sample, not raw volume: 500k rows here, tens of millions elsewhere, root-caused in ~90s.
- **"Where do the scripts come from?"** — `trace_job` auto-discovers the building job's SQL from Unity Catalog lineage; source values/types come from the recon output. No manual script-passing.
- **"How is a difference classified?"** — migration-induced (fix the code), genuine-data (route to owners), expected (no action), needs-review (investigate). "Actionable" = migration + genuine.
