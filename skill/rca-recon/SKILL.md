---
name: rca-recon
description: >-
  Automate root-cause analysis of Lakebridge reconciliation mismatches for a
  data-warehouse migration (e.g. Snowflake -> Databricks). Given a Lakebridge
  reconcile recon_id, generate and run a live RCA notebook that explains every
  mismatch, classifies each as migration-induced / genuine data difference /
  benign / needs-review, and produces a TL;DR with remediation and owner. Use
  when the user gives a recon id, mentions Lakebridge/remorph reconcile RCA, or
  asks why reconciled tables differ.
---

# Lakebridge Reconciliation RCA

Turn a Lakebridge `reconcile` result into a finished root-cause analysis. You run
**live** inside the workspace: generate a notebook, execute drill-down queries,
refine hypotheses, and keep going until every finding has a confident verdict or
is explicitly flagged **needs review**. After the notebook is generated, **ask the
user to approve it before running all cells** (see Workflow step 5).

## Input contract

- **Required (from the user):** `recon_id` — the Lakebridge reconcile run id.
- **Optional (from the user):** where to save the RCA notebook. If the user gives a
  location (a UC Volume like `/Volumes/cat/sch/vol`, a workspace path, or any dir),
  use it; otherwise fall back to `output_dir` in `config.yml`. The default is a bare
  folder name (`rca_notebooks`) that resolves under the user's workspace home
  (`/Workspace/Users/<current_user>/rca_notebooks`). It is fine to ask "Where should
  I save the RCA notebook?" if the user hasn't said.
- **From `config.yml` (this skill folder):** `recon_catalog`, `recon_schema`,
  `dialect` (the original source EDW dialect, e.g. `snowflake`), `output_dir`, and an
  optional `warehouse_id`. Read it with a small YAML load; do not ask for these.

## Verdict taxonomy (this is the field the human acts on)

- **Migration-induced** — fix in the migration (type mapping, timezone
  normalization, transpiled SQL, pipeline filter/join, null/boolean encoding,
  string normalization). Owner: migration engineer.
- **Genuine data difference** — the source/upstream data really differs (e.g. a
  column NULL in source but populated in target, or a stale snapshot). Owner:
  data owner / source team. **Not** a migration bug.
- **Benign / expected** — semantically-equal representation difference (e.g. JSON
  key reordering) or within tolerance. No action.
- **Needs review** — evidence inconclusive; state exactly what to check next.

## Workflow

### 1. Set up the engine
The deterministic engine (`rca_engine`) is **vendored inside this skill folder**,
so no package install is needed — just add the skill folder to `sys.path` and
import it. Do **not** `pip install` from an external URL.

```python
import os, sys
SKILL_DIR = os.getcwd()          # the notebook runs from this skill folder
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
import rca_engine                 # resolves to ./rca_engine (vendored)
```

### 2. Run the end-to-end engine (ingest → classify → live drill-down)
Use the in-notebook Spark session as the query backend. `analyze()` reads
`main`/`metrics`/`details`, runs deterministic probes, **and then executes a live
confirmation query per finding** (attaching the query + result as evidence and
finalizing the verdict/confidence). This is the concluded result — not a guess.

```python
import yaml
from rca_engine.runners import SparkQueryRunner
from rca_engine.analyze import analyze
from rca_engine.report import build_tldr, write_json, write_notebook

import os
cfg = yaml.safe_load(open("config.yml"))            # relative to this skill folder
recon_id = "<RECON_ID_FROM_USER>"

# Resolve save location: absolute path used as-is; a bare folder name goes under
# the user's workspace home. Prefer scripts/run_rca.py which does this for you.
raw = "<USER_LOCATION_OR_NONE>" or cfg.get("output_dir", "rca_notebooks")
if raw.startswith("/"):
    out_dir = raw
else:
    user = spark.sql("SELECT current_user() AS u").collect()[0][0]
    out_dir = f"/Workspace/Users/{user}/{raw}"
os.makedirs(out_dir, exist_ok=True)

result = analyze(
    SparkQueryRunner(spark), recon_id,
    cfg["recon_catalog"], cfg["recon_schema"],
    dialect=cfg.get("dialect", "snowflake"), drilldown=True,
)
print(build_tldr(result))
write_notebook(result, os.path.join(out_dir, f"rca_{recon_id}.ipynb"))  # symbol-coded report
```

`scripts/run_rca.py` also accepts the location: `run(recon_id, spark, out_dir=...)`
(priority: explicit arg > `config.output_dir` > `rca_notebooks` under the user's
workspace home).

`scripts/run_rca.py` wraps exactly this. See `references/taxonomy.md` for how
probes map to categories.

### 3. Go deeper on anything unresolved
`analyze()` already confirms the common cases. For any finding still at
confidence < 0.8, verdict `needs_review`, or where the user wants proof, run an
extra query and update the finding. Useful patterns (source = `main.source_table`,
target = `main.target_table`):

- **type_precision / transpilation (numeric):** compare rounded vs raw, and check
  the aggregation/transform SQL for `ROUND`, casts, or scale changes.
  `SELECT <key>, s.<col> src, t.<col> tgt, s.<col>-t.<col> d FROM source s JOIN target t USING(<key>) WHERE s.<col> <> t.<col> LIMIT 50`
- **timezone:** confirm the offset is constant across rows:
  `SELECT DISTINCT unix_timestamp(t.<col>) - unix_timestamp(s.<col>) AS off FROM ...` — one value ⇒ tz normalization.
- **null_boolean:** confirm whether it is NULL-vs-empty or an encoding map:
  `SELECT s.<col> src, t.<col> tgt, count(*) FROM ... GROUP BY 1,2`.
- **upstream_drift / genuine data (provenance):** verify the source really is
  NULL/stale — `SELECT count(*) FROM source WHERE <col> IS NULL` (if source is
  NULL and target populated, it is a genuine data difference, not a migration bug).
- **volume_missing / volume_extra:** bucket the gap to find a filter/watermark or
  fan-out — group missing keys by a date/dimension; high concentration ⇒ bounded
  filter/watermark; spread ⇒ dedup/fan-out. Use `rca_engine.rowpattern.analyze_buckets`.
- **string_format:** `SELECT s.<col>, t.<col> FROM ... WHERE trim(lower(s.<col>))=trim(lower(t.<col>)) AND s.<col><>t.<col>` — trim/case only ⇒ formatting.

Update each finding's verdict/confidence with what the query shows. Iterate until
resolved. Do **not** stop if anything is unresolved.

### 4. Produce the RCA notebook + conclusion
- `write_notebook(result, os.path.join(out_dir, f"rca_{recon_id}.ipynb"))` emits a
  symbol-coded report to the user-chosen `out_dir`, structured to mirror Lakebridge:
  1. **🧭 RCA Summary** — verdict counts (with meaning) for the whole `recon_id`.
  2. **📋 Reconciliation overview** — one row per table pair showing schema,
     row-level (missing in target / extra in target), mismatched columns, and a
     verdict rollup — the same breakdown Lakebridge reports.
  3. **📈 Match rates** — overall **row-level** and **column-level match %** for
     *every* table pair (including clean ones), not just the issues.
  4. **📅 Validation (date-range filterable)** — `dbutils.widgets` for
     `start_date`/`end_date` plus `validate_rows()` / `validate_column()` helpers
     and per-table calls, so the user can re-check row/column match % for any window.
  5. **🎯 Findings by verdict** — action tables (what to fix vs route).
  6. **🔬 Findings & evidence** — grouped by table pair, ordered schema → row-level
     → column-level; each finding has category/confidence/owner, root cause, fix,
     the confirming query + its evidence, and sample diffs.
  7. **🧾 Conclusion & recommended actions** — grouped by owner.
- The markdown is rendered from the concluded result, so every verdict is already
  backed by an executed drill-down query, and per-column counts are reconciled to
  the exact number of differing rows (recon `details` only stores a sample).

### 5. Confirm with the user, then run all cells
- After writing the notebook, **pause and ask the user for approval** before
  executing it. Show the TL;DR and the actual saved path, then ask explicitly, e.g.:
  _"The RCA notebook is generated at `<out_dir>/rca_<recon_id>.ipynb`. Are the
  findings and proposed fixes acceptable? Reply **yes** to run all cells, or tell me
  what to adjust."_
- **Do not run the notebook until the user confirms.** If they request changes
  (reclassify a finding, add a drill-down, tweak a fix/owner), apply them, regenerate
  the notebook, and ask again.
- **On approval, run all cells** top-to-bottom so every confirming query executes
  live and the outputs are captured in the notebook.

### 6. Reconcile the conclusion with the executed outputs (always)
After running all cells, **read each query's output and check it still supports the
written verdict/confidence in that finding's markdown** (and the TL;DR + Conclusion
sections):
- If an output matches the stated conclusion, leave it.
- If an output changed the picture (e.g. offset is no longer constant, source is
  actually populated, extra rows are duplicates not new keys), **update that
  finding** (verdict, confidence, rationale, owner) and **regenerate the notebook**
  (`write_notebook`) so the TL;DR and 🧾 Conclusion always match the evidence.
- If any finding is still unresolved, mark it **needs review** with the exact next
  query/owner. Then restate the final verdict counts to the user.

Never leave a conclusion that contradicts a cell's output — the markdown and the
executed evidence must agree.

## Rules

- Never label something migration-induced without checking it could be a genuine
  data difference (especially NULL-in-source, stale-snapshot, and partial-column
  mismatches). When source is NULL/absent and target is populated, it is genuine
  data unless proven otherwise.
- Prefer deterministic evidence (a query result) over narrative. Every verdict
  must cite the query that supports it.
- If a mismatch cannot be explained after drill-down, mark it **needs review** and
  say exactly which query/owner would resolve it. Do not guess.

## Examples

**Example 1 — full run from a recon id**
- User: _"Run an RCA on Lakebridge reconcile `recon_id=0fe6...b747bf`."_
- You: load `config.yml`, `run(recon_id, spark)`, print the TL;DR, save the notebook
  under `/Workspace/Users/<user>/rca_notebooks/`, then ask for approval. On "yes",
  run all cells and reconcile. Expected shape of the answer:
  _"9 migration-induced, 3 genuine data differences, 1 benign. Fix in migration:
  `fact_order_items.amount` (DECIMAL→DOUBLE scale loss), `fact_orders.order_ts`
  (constant 5.5h tz offset), `agg_daily_sales.revenue` (ROUND diff)… Route to data
  owner: `dim_customer.loyalty_tier` (NULL in source, populated in target)…"_

**Example 2 — custom save location**
- User: _"RCA recon `abc123` and save it to `/Volumes/main/rca/out`."_
- You: pass `out_dir="/Volumes/main/rca/out"` (absolute → used as-is).

**Example 3 — a genuine data difference (not a migration bug)**
- Finding: `dim_customer.loyalty_tier` differs; drill-down `SELECT count(*) ... WHERE
  loyalty_tier IS NULL` shows the source is NULL for those rows while the target is
  populated. Verdict: **📊 Genuine data difference**, owner = data owner. Do **not**
  file it as a migration defect.

## Edge cases

- **No mismatches**: recon is clean → report "no differences found for `recon_id`"; do
  not fabricate findings.
- **Sampled vs true counts**: recon `details` stores only a sample; trust `metrics`
  for row-level counts and use the drill-down query's exact count for per-column
  counts (the engine already reconciles this).
- **`_null_recon_` sentinel**: Lakebridge writes `_null_recon_` for NULLs in details;
  treat it as NULL (the engine's null probe already does).
- **Aggregate/derived tables** (e.g. `agg_daily_sales`) have no 1:1 source row, so
  join-key drill-downs may not apply — compare at the aggregated grain instead.
- **Missing join keys**: if a finding has no usable key for a live query, fall back to
  a grouped/`LIMIT` inspection and lower confidence accordingly.
- **Large tables**: keep drill-down queries aggregate (counts/min/max), not full row
  dumps, to stay within the warehouse budget.
- **Unresolved after drill-down**: mark **needs review** with the exact next step;
  never force a verdict.
