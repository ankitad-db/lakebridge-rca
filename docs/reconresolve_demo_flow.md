# ReconResolve — 3-Minute Demo Flow

**App:** https://rca-genie-7474660494970929.aws.databricksapps.com — **hard-refresh once (Cmd+Shift+R)** before you start.
**Showcase recon (deep-dive):** `446d22cd1d2b40d7a4f6efdf1fdc3bdc`
**Live-run recon (watch it work):** `218dab3c4c51443783dbf14a16c324fc`

> ⚠️ **Do NOT click "Run full RCA" on `446d22`.** It's pre-analyzed with the source-vs-target
> lineage; re-running it regenerates the bundle and drops that detail. Run the live demo on
> `218dab` only.
> ⏱️ **Cadence:** kick off the `218dab` run first (step 1), then spend the wait on `446d22`.
> A full run takes ~2 min; by the time you come back it's done.

---

## 1 · Recon runs → kick off a live RCA (20s)
**Show:** Left nav → **Recon runs**. Find `218dab…`. Note the **mode toggle** (Deterministic / Hybrid).
Click **▶ Run full RCA & generate notebook**. A banner shows *"Analyzing all tables…"*.
**Say:** *"ReconResolve starts from a Lakebridge `recon_id`. Pick it, choose Deterministic or Hybrid, and run — it root-causes every difference and writes a notebook. That runs as a job; while it works, let's look at the bigger picture and a recon that's already done."*

---

## 2 · Migration Health — the leadership view (35s)
**Show:** Left nav → **Migration Health**.
**Say:** *"The migration-wide roll-up. KPIs — recons run, tables reconciled, findings, and the **actionable** count. The **verdict mix** — migration-induced vs genuine-data vs expected vs needs-review. And the **top recurring root causes** — timezone, precision, string-format. One glance answers: how healthy is the migration, and where's the work?"*
**Point at:** the verdict-mix bar + the top-causes bars.

---

## 3 · Open the showcase recon dashboard (30s)
**Show:** **Recon runs** → click **`446d22…`** to open its dashboard.
**Say:** *"A retail Sales & Revenue mart, Snowflake→Databricks. **Rows matched: 99.8%** — a stray load filter dropped about 1,000 of 500,000 orders. **Columns changed: 3.** So two kinds of problem at a glance: some rows missing, and — more dangerous — the rows that ARE there have wrong values."*
**Point at:** the **Rows matched** and **Columns changed** KPI tiles, then the **`fact_sales`** row in the table.

---

## 4 · The finding — the money moment (60s)
**Show:** In the table, click **`fact_sales`** → expand the **`order_ts_utc`** finding.
**Say (issue):** *"Every order's timestamp is 5 hours late. The migration added a flat +5 hours to 'normalise to UTC', but the source was already canonical — so evening orders roll to the next day and daily revenue reports are wrong."*
**Point at the lineage block (top of the finding):**
- **Source · EDW:** `fact_sales.order_ts_utc` = `r.order_ts`
- **🔧 Migrated transform:** `r.order_ts + INTERVAL '5' HOURS` · `revenue_target.sql:32`
- **Target ⚠:** `fact_sales.order_ts_utc` · rows affected
**Say (proof + solution):** *"You see it side-by-side: source logic vs the migrated logic that broke it — with the script and line. Below: the **Root cause**, the **Solution / fix** ('convert TIMESTAMP_LTZ/TZ to UTC'), the owner, and a **✔ query-confirmed** badge — a confirming query found a constant 5-hour offset on every order. Deterministic, no AI — proven, not guessed."*
**Optional (10s):** collapse it, expand the **dropped-rows** finding → its block shows `500,000 rows → load filter WHERE order_id % 500 <> 0 → 499,000 rows, 1,000 missing`.

---

## 5 · The notebook — come back to the live run (25s)
**Show:** Left nav → **Recon runs** → `218dab…` (the run from step 1 is now **done** — a green banner with **Open in workspace ↗**). Click it.
**Say:** *"And the run we kicked off is finished — it published a runnable notebook to the workspace: a mode banner, per-table root-cause sections, the verdicts, and the reproduction query for every finding. That's the same analysis, as an artifact your engineers can run and hand off."*
**Point at:** the notebook's top banner + one table section. (Don't deep-dive — just show it exists and is structured.)

---

## 6 · Close (10s)
**Say:** *"Every reconcile difference — root-caused, shown source-vs-target, query-backed, with a fix and an owner, and a notebook to prove it. **Lakebridge reconciles. ReconResolve resolves.**"*

---

### If asked
- **"Is it AI?"** — Not for this recon; every finding is a rule + a confirming query. Hybrid adds a query-gated Foundation-Model tier only for the hard transforms — the model proposes, a query confirms, a guess never sticks.
- **"Does it scale?"** — RCA runs on the bounded recon sample, not raw volume: 500k here, tens of millions elsewhere, ~90s.
- **"Which dialects?"** — Exactly Lakebridge's reconcile set: databricks, snowflake, oracle, mssql, synapse, redshift, teradata.

### Safe fallback (zero-risk, if you'd rather not run live)
Skip step 1 and step 5's live run. In step 5, show the **already-generated** `446d22` notebook instead
(Recon runs → 446d22 → the notebook link), or just close after step 4. The deep-dive on `446d22`
(steps 3–4) is the core of the demo and needs no live run.
