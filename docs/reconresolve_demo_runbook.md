# ReconResolve — demo runbook (all entry points × deterministic & hybrid)

One place to run the demo three ways, in both modes. Everything lands under a single workspace
home so a reviewer can open any variant:

```
/Workspace/Users/ankita.darekar@databricks.com/reconresolve/
├── 00_RUNBOOK              this runbook (notebook)
├── artifacts/             the migrated-SQL artifacts (hybrid_target.sql, det_target.sql, xl_target.sql)
├── cli/
│   ├── deterministic/     rca_<recon_id>/  (CLI, no LLM)
│   └── hybrid/            rca_<recon_id>/  (CLI, --endpoint)
├── skill/
│   ├── deterministic/     rca_<recon_id>/  (Genie Code skill, llm off)
│   └── hybrid/            rca_<recon_id>/  (Genie Code skill, endpoint)
└── app/                   (the App publishes into its own bundles; URL below)
```

## The demo recon_ids (genuine Lakebridge reconcile on `ps-dr-east`)

| Bed | recon_id | Use for |
|---|---|---|
| **Hybrid** (Snowflake→Databricks retail, 2M) | `218dab3c4c51443783dbf14a16c324fc` | deterministic **or** hybrid — has 3 defects only the agentic tier can name |
| **Deterministic** (same shape, clean defects) | `eca72dd859f246088271a0ac0e43ddae` | pure Tier-1 walk-through (13 findings) |
| **Aggregate** (`aggregates-reconcile`) | `d90e15507e02494190c6d87cd59123bf` | per-rule SUM/AVG-by-group RCA |
| **Prod-volume** (50M wide, ~17 GB) | `5a87fd6e84ee441e8c744b6dfe7061fe` | "survives prod volume?" — reconcile 27 min, RCA ~97 s |

## What the two modes mean (same on every entry point)

- **Deterministic** — Tier-1 only: rule-based probes + one live confirming query per finding. **No LLM.**
  Reproducible & auditable. Still shows the 🔧 transformation logic, ⚠️ culprit, 📄 script location,
  confidence, and UC lineage (parsed/queried deterministically).
- **Hybrid** — deterministic first, then a **query-gated Foundation-Model fallback** on the residual the
  rules can't name — a model cause is promoted **only if** its confirming query matches.

---

## A) Genie Code skill

Open **Genie Code (Agent mode)** in the workspace and prompt:

```
Root-cause reconciliation eca72dd859f246088271a0ac0e43ddae
```
- Deterministic is the deployed skill default (`config.yml`: `llm_synthesis:false`).
- For **hybrid**, either flip `config.yml` (`llm_synthesis:true` + `llm_endpoint: databricks-claude-opus-5`)
  or say so in the prompt:
  ```
  Root-cause reconciliation 218dab3c4c51443783dbf14a16c324fc using the databricks-claude-opus-5 endpoint for the residual findings
  ```
- First time per session, run the setup cell so the code-aware parse works:
  ```python
  %pip install sqlglot pyyaml
  dbutils.library.restartPython()
  ```
- Output bundle: `…/rca_notebooks/rca_<recon_id>/` → open `fact_sales`.

## B) CLI (for CI/CD & Genie-restricted workspaces)

```bash
# Deterministic
python -m rca_engine.cli --recon-id eca72dd859f246088271a0ac0e43ddae \
  --recon-catalog fevm_ps_dr_us_east_2_catalog --recon-schema reconcile --dialect snowflake \
  --warehouse-id 3220376d4497e2d7 --profile ps-dr-east \
  --transpiled-output migration/retail_demo/det_target.sql --output-dir /tmp/cli_det

# Hybrid — add the FM endpoint
python -m rca_engine.cli --recon-id 218dab3c4c51443783dbf14a16c324fc \
  --recon-catalog fevm_ps_dr_us_east_2_catalog --recon-schema reconcile --dialect snowflake \
  --warehouse-id 3220376d4497e2d7 --profile ps-dr-east \
  --transpiled-output migration/retail_demo/hybrid_target.sql \
  --endpoint databricks-claude-opus-5 --output-dir /tmp/cli_hyb
```
Add `--use-lineage` for the UC lineage trace-back + blast radius.

## C) Databricks App

Open **https://rca-genie-7474660494970929.aws.databricksapps.com** →
1. In the sidebar (or at any Analyze action), set **RCA MODE**: *Deterministic* or *Hybrid (deterministic + agentic fallback)*.
2. **Recon runs** → pick a recon_id → **Analyze table-by-table** (or the run dashboard → *Run full RCA*).
3. Each finding shows conf% + ✓ confirmed; the dashboard shows an **Avg confidence** rollup.

---

## What to check in every notebook (all entry points, both modes)

Open `fact_sales` and look at each finding for:
- **🔧 Transformation logic** — the migrated derivation (`col = <expr>`)
- **📄 Script location** — the exact `<path> · line N` where the transform lives, + the raw script line
- **⚠️ Likely culprit** — the specific sub-expression (`ROUND(…,2)`, `+ INTERVAL '5 HOURS'`, `UPPER(…)`, the `CASE`, the `WHERE`)
- **Category · Confidence · ✓ confirmed** — verdict + a re-runnable confirming query
- **Evidence (lineage)** — UC upstream trace-back + downstream blast radius
- **Hybrid only:** `net_revenue` (missing discount×tax cross-term), `amount_usd` (FX month-start grain),
  `status_bucket` (dropped `'R'` CASE branch) — each **agentic, query-confirmed @ 95%**

Benchmarks & feature detail: `docs/BENCHMARKS.md`, `docs/reconresolve_leadership_deck.html`.
