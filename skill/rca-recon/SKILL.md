---
name: rca-recon
description: >-
  Automate reconciliation AND root-cause analysis of a data-warehouse migration
  (e.g. Snowflake -> Databricks). Two entry points, one skill: (A) given source +
  target tables, trigger a reconcile (auto-detecting join keys) to produce a
  recon_id, then run RCA on it; or (B) given an existing Lakebridge reconcile
  recon_id, run RCA directly. RCA generates and runs a live notebook that explains
  every mismatch, classifies each as migration-induced / genuine data difference /
  benign / needs-review, and produces a TL;DR with remediation and owner. Every
  reconcile/RCA step is recorded in an append-only audit table. Use when the user
  gives a recon id, asks to reconcile tables, mentions Lakebridge/remorph reconcile
  RCA, or asks why reconciled tables differ.
---

# Lakebridge Reconciliation RCA

**RCA is the step *after* Lakebridge `transpile` + `reconcile`.** The Lakebridge flow
is: analyze → **transpile** (convert source SQL → Databricks) → **reconcile** (compare
source vs. target) → **RCA (this skill)**. Turn a Lakebridge `reconcile` result into a
finished root-cause analysis. You run **live** inside the workspace: generate a
notebook, execute drill-down queries, refine hypotheses, and keep going until every
finding has a confident verdict or is explicitly flagged **needs review**. After the
notebook is generated, **ask the user to approve it before running all cells** (see
Workflow step 5).

When the upstream Lakebridge artifacts are available, RCA is **code-aware**: it reads
the transpile output and recon config to confirm a mismatch's cause from the actual
translated code (not just from the data). See the optional inputs below.

**This one skill covers both the reconcile and the RCA step.** If the user does not
have a `recon_id` yet but can name the source/target tables, trigger the reconcile
first (Workflow step 0) — that produces a `recon_id`, which flows straight into the
same RCA flow. If the user already has a `recon_id`, skip straight to RCA (step 2).
Every step is recorded in an audit table (see "Audit trail").

## Input contract

- **One of (from the user):**
  - `recon_id` — an existing Lakebridge/reconcile run id → run RCA directly (step 2), **or**
  - **source + target tables** to reconcile (e.g. `mig_source_sim.dim_customer` →
    `mig_target.dim_customer`) → trigger a reconcile first (step 0), which yields a
    `recon_id`. Join keys are optional (auto-detected); renamed columns take a
    `column_mapping`.
- **Optional (from the user):** where to save the RCA notebook. If the user gives a
  location (a UC Volume like `/Volumes/cat/sch/vol`, a workspace path, or any dir),
  use it; otherwise fall back to `output_dir` in `config.yml`. The default is a bare
  folder name (`rca_notebooks`) that resolves under the user's workspace home
  (`/Workspace/Users/<current_user>/rca_notebooks`). It is fine to ask "Where should
  I save the RCA notebook?" if the user hasn't said.
- **From `config.yml` (this skill folder):** `recon_catalog`, `recon_schema`,
  `dialect` (the original source EDW dialect — any Lakebridge source; KBs ship for
  `snowflake`/`oracle`/`teradata`/`mssql`/`synapse`, unknown dialects still run with generic
  probes), `output_dir`, an
  optional `warehouse_id`, the default `source_schema`/`target_schema` for the
  reconcile step, and `audit_table`. Read it with a small YAML load; do not ask for these.
- **Optional (code-aware RCA) — from `config.yml`:** the RCA confirms causes from the
  code, not just the data, using any subset of:
  - `recon_config_path` — reconcile config JSON = **the mapping** (exact join keys,
    column mapping, filters). Reused as-is; no separate hand-written mapping file needed.
  - `transpiled_output_dir` — **target scripts**: the deployed/transpiled Databricks SQL
    (in future, `lakebridge transpile --output-folder`) → per-column transforms
    (e.g. `MAKE_INTERVAL` proves a tz shift; `WHERE order_id <= 480` proves a watermark;
    a target-generated column not carried from source is pulled to needs-review).
  - `source_scripts_dir` — **source scripts**: original-dialect DDL → declared source
    types (e.g. source `NUMBER(18,4)` vs target `DECIMAL(18,2)` = confirmed scale loss;
    `TIMESTAMP_LTZ` confirms a tz normalization is required).
  - `transpile_error_file` — Lakebridge `transpile --error-file-path` report → its own
    flagged/failed translations, cited as evidence.
  - `tables:` — an explicit **per-table manifest** (`target`, `source_script`,
    `target_script`, optional `join_keys`/`date_column`) that overrides the folder scans
    when file↔table names are ambiguous. Most robust way to pass scripts.
  - `use_uc_lineage: true` — attach **Unity Catalog lineage** evidence
    (`system.access.column_lineage`/`table_lineage`): confirms a column's true upstream
    provenance and the upstream tables feeding a target (helps locate where a
    volume/drift cause entered). Also performs a **depth-agnostic trace-back**: it walks
    lineage hop by hop (column lineage where a column is known, table lineage otherwise)
    to the root layer, so a defect that entered several layers upstream (e.g. an
    intermediate staging/transform table) is pointed at directly — not just the
    reconciled target. `max_lineage_hops` (default 10) bounds the walk depth; it stops
    early at the roots. Degrades to nothing if lineage isn't captured.
  - `use_memory: true` — **learning loop**. Before analysis, load priors from previously
    **confirmed** runs (a Delta memory table keyed by a mechanism signature = dialect +
    category + translated functions / scale delta) and propose a matching recurring cause
    — which the drill-down then confirms (never promoted on memory alone). After the run,
    every query-confirmed cause is recorded, so the same mistranslation/scale-loss
    auto-classifies next time. Shows as a **📚 learned prior** input. Off by default.

  Each finding is cross-confirmed by up to five independent sources (recon data +
  target code + source types + UC lineage + live query), shown per finding as
  **"Inputs used"**. Requires `sqlglot` (`pip install sqlglot`) for the
  script parsing; if absent, RCA degrades gracefully to data-driven mode. Omit all for a
  pure data-driven run.

- **Always-on enrichment (no config needed):**
  - **Systemic root-cause clustering** — findings that share one mechanism (a mistranslated
    expression, a transpile warning, one category concentrated in a table) are grouped into
    a single **🧨 Systemic root causes** table so you fix *one* thing and clear N. Spans
    tables when the same translation defect recurs.
  - **Distribution drift** (`distribution_drift: true`, default on) — for every column
    mismatch, measures source-vs-target **null-rate, cardinality, and numeric summary**
    (min/max/mean/stddev) and reports the shift. A stable distribution points to a
    migration/precision cause; a material shift (null-rate jump / cardinality change) points
    to a **genuine upstream data difference** — quantifying the migration-vs-genuine call.
  - **Downstream blast radius** (`blast_radius`, defaults to `use_uc_lineage`) — for each
    *affected* target table, lists the UC tables that consume it (from
    `system.access.table_lineage`) so a fix is prioritized by how far the defect propagates.
    Rendered as a **💥 Downstream blast radius** table. Degrades to nothing if lineage is
    unavailable.
  - **Suggested fixes** (`suggest_fixes: true`, default on) — attaches a concrete,
    **runnable** remediation to each finding: a corrected transform expression (widen a
    cast, normalize a timezone, align TRIM/case, explicit NULL/boolean mapping), a load
    statement (back-fill missing rows via `LEFT ANTI JOIN`, de-duplicate extras via
    `row_number()`), or a recon-config normalization. Deterministic; always a
    **suggestion** — rendered as a review-then-run **🛠️** cell and rolled up in a
    **Suggested fixes** table, never auto-applied.
  - **Fix-validation gate** (`validate_fixes: true`, default on) — each fix carries a
    validation query that checks the reconciliation gap is *entirely* explained by the
    mechanism the fix corrects (e.g. every mismatch is `round(source, tgt_scale)`, or a
    single constant TZ offset, or trim/case only, or the missing/duplicate keys). Fixes
    that pass are marked **✅ validated**; the rest stay unvalidated suggestions. Same
    discipline as verdicts: nothing is presented as trusted unless a query confirms it.
  - **Scan scoping** (`scan_mode: scoped`, default) — the live confirming, drift, and
    fix-validation queries are bounded so they don't full-scan source and target: a column
    confirm re-checks only the reconciliation-**flagged keys** (`IN (...)` push-down), and
    full-table aggregates are restricted to the `scan_partition_column` / `scan_date_*`
    window when set. This is **exact** — the true total mismatch count still comes from the
    recon metrics, and key-scoped confirms are annotated `[scoped to flagged keys]`. Set
    `scan_mode: full` for the original unbounded scans.

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

### 1b. (If the user doesn't have a recon_id) discover recent runs
If the user hasn't given a `recon_id`, list recent reconcile runs and let them pick.
Do **not** guess a `recon_id`.

```python
from scripts.run_rca import list_runs
list_runs(spark)                 # prints a table of recent recon_ids + which have diffs
```
(or `from rca_engine.discovery import list_recon_runs, format_recon_runs`).

### 0. (If there is no recon_id yet) trigger the reconcile
When the user gives **source/target tables instead of a `recon_id`**, reconcile them
first. This compares each pair on the warehouse/Spark session and writes
Lakebridge-compatible `main`/`metrics`/`details` rows under a fresh `recon_id` in
`recon_catalog.recon_schema` — the exact input the RCA step reads. Join keys are
**auto-detected** when omitted (unique + non-null id-like columns, capped at
`max_key_tries`); renamed columns take a per-pair `column_mapping`; each pair is
isolated so one failure never sinks the run.

```python
from scripts.run_rca import reconcile_and_run

# tables: bare "name" (source==target) or {source, target?, join_keys?, column_mapping?}
recon_id, result = reconcile_and_run(
    spark,
    source_schema="mig_source_sim",     # defaults to config.source_schema
    target_schema="mig_target",         # defaults to config.target_schema
    tables=[
        "dim_customer",
        {"source": "edge_geo", "column_mapping": {"country": "country_name"}},
        {"source": "fact_orders", "join_keys": ["order_id"]},
    ],
)
# reconcile_and_run == reconcile(...) then run(recon_id, spark). To only reconcile
# (get a recon_id to hand off / run RCA later), call reconcile(...) alone.
```

The resulting `recon_id` is exactly what the **separate RCA path** (step 2) also
takes — so a user can reconcile now and run/re-run RCA on that `recon_id` any time.

### 2. Run the end-to-end engine (ingest → classify → live drill-down)
Use the in-notebook Spark session as the query backend. `analyze()` reads
`main`/`metrics`/`details`, runs deterministic probes, **and then executes a live
confirmation query per finding** (attaching the query + result as evidence and
finalizing the verdict/confidence). This is the concluded result — not a guess.

**Setup (run FIRST, once per session).** The code-aware transformation-logic callout and
the agentic reconstruction parse the migrated SQL with **`sqlglot`**. It is a public PyPI
package (not the vendored engine — installing it is fine and unrelated to the "no external
install" rule for `rca_engine`). Install it **before importing the engine**, because
sqlglot availability is bound at import time — if it's missing you still get lineage/verdicts
but **no `🔧 Transformation logic`**:

```python
%pip install sqlglot pyyaml
dbutils.library.restartPython()
```

**Run it with `run()` — do NOT call `analyze()` directly.** `run()` reads `config.yml` and
wires in everything the concluded report needs: the code-aware **mapping** built from
`transpiled_output_dir` (this is what produces the **🔧 Transformation logic** callout and
the agentic reconstruction), the **scan scope**, distribution drift, UC lineage, suggested
fixes + validation, and — when `llm_synthesis`/`llm_endpoint` is set — the Tier-2 agentic
refinement. A bare `analyze(...)` call skips the mapping, so the notebook shows **no
transformation logic** and unscoped counts — don't use it as the entry point.

```python
from scripts.run_rca import run

recon_id = "<RECON_ID_FROM_USER>"
# Everything (recon_catalog/schema, dialect, transpiled_output_dir for the transform-logic
# highlight, scan scope, llm_synthesis/llm_endpoint for the agentic tier, output location)
# comes from config.yml. Override per run only if asked:
#   run(recon_id, spark, out_dir="/Volumes/...")            # different save location
#   run(recon_id, spark, transpiled_output_dir="/Workspace/.../another_migration")
#   run(recon_id, spark, llm_endpoint="")                   # force pure-deterministic
result = run(recon_id, spark)
```

`run()` writes one self-contained folder per recon run and registers each notebook so it
renders:

```
<out_dir>/rca_<recon_id>/
    00_index.ipynb        overview + per-table routing (multi-table runs)
    rca_<recon_id>.json   full findings
    <table>.ipynb         one notebook per reconciled table (each column finding carries
                          its 🔧 Transformation logic derivation, verdict, and confirm query)
```

If you need the lower-level pieces (e.g. to add your own drill-down after the concluded
result), `run()` internally does: build the mapping from the `config.yml` artifacts →
`analyze(runner, recon_id, catalog, schema, dialect=…, mapping=mapping, scope=…, …)` →
`write_rca_bundle(...)`. Always pass `mapping=` if you call `analyze()` yourself, or the
transformation logic will be missing.

`scripts/run_rca.py` also accepts the location: `run(recon_id, spark, out_dir=...)`
(priority: explicit arg > `config.output_dir` > `rca_notebooks` under the user's
workspace home).

`scripts/run_rca.py` wraps exactly this. See `references/taxonomy.md` for how
probes map to categories.

> **Headless invocation (from the ReconResolve App).** The app runs this skill without
> a human in the loop by submitting `scripts/job_entry.py` as a **serverless Databricks
> Job**. That driver reads job parameters (`mode`, `recon_id`, `source_schema`,
> `target_schema`, `tables_json`, `out_dir`, `only_table`), overlays `config.yml` with the
> `RCA_CONFIG_JSON` env it sets (so catalog/schema/dialect/output_dir/audit come from the
> app), calls `reconcile` / `run` / `reconcile_and_run` here, and returns
> `{recon_id, folder, findings, tables}` via `dbutils.notebook.exit`. Same code, same
> outputs — the app just reads the written bundle back. Nothing you do interactively changes.

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

### 3b. Tier 2 — your (Genie Code) LLM fallback for the residual long tail
The engine's probes + templated drill-down are a **deterministic first pass**: they
resolve the *known* mismatch mechanisms. Whatever they cannot explain is left as
`needs_review` / `unknown`. **This is where you (the LLM) add value** — reason over
*just those residuals*, but stay evidence-first: you propose a cause **and a
confirming SQL query**, the engine runs it, and the verdict is promoted **only if the
query confirms it**. You never set a verdict on opinion alone.

```python
from rca_engine.resolve import unresolved_findings, build_evidence_bundle, resolve_finding
from rca_engine.runners import SparkQueryRunner

runner = SparkQueryRunner(spark)
for f in unresolved_findings(result):          # only NEEDS_REVIEW / UNKNOWN findings
    bundle = build_evidence_bundle(f, mapping=mapping, dialect=cfg.get("dialect", "snowflake"),
                                   runner=runner)   # runner enables a live UC-lineage trace-back
    # bundle = { source/target tables, column, sampled value pairs, declared
    #            source_type, transpiled target_derivation, transpile_issues,
    #            prior_evidence (code/transpile/recon_config/lineage/drilldown already
    #            gathered), and lineage {upstream_tables, column_upstreams, trace_back:
    #            {paths, roots, max_depth}} — a full hop-by-hop chain to the root layer,
    #            so you can walk PAST the first hop and issue a confirming query at
    #            whichever upstream layer the difference actually entered. }
    #
    # ↳ YOU reason over `bundle`: form the most likely root-cause category and a
    #   confirming query. The query MUST return a boolean `confirmed` column (and
    #   ideally an `n` count) so the engine can gate on it. Example for a suspected
    #   collation/encoding difference the probes missed:
    resolve_finding(
        f, runner,
        category="string_format",                       # your hypothesised category
        rationale="target upper-cases the code; equal after UPPER() on both sides",
        confirm_query=(
            f"SELECT (count(*) = sum(CASE WHEN upper(s.`{f.column}`)=upper(t.`{f.column}`) "
            f"THEN 1 ELSE 0 END)) AS confirmed, count(*) AS n "
            f"FROM {f.source_table} s JOIN {f.target_table} t USING (id) "
            f"WHERE s.`{f.column}` <> t.`{f.column}`"
        ),
        # verdict is inferred from the category if omitted; pass it explicitly for
        # genuine-data cases, e.g. verdict="genuine_data".
    )
```

- `resolve_finding` returns `True` and attaches a high-confidence, **query-backed**
  hypothesis only when the query confirms it; otherwise it leaves the finding at
  `needs_review` and records your proposal as the *suggested next check*.
- Keep queries **aggregate** (counts / min / max / boolean), not row dumps.
- Run this tier for `unresolved_findings(result)` (the residual). To also generate a
  query for findings the deterministic pass only covered with a **generic template**
  (no targeted confirming query yet), use `needs_query(result)` — the same
  `resolve_finding` gate applies, so nothing is promoted without an executed query.
  Leave findings that already have a deterministic drill-down query alone.
- After this tier, still mark anything you could not confirm as **needs review**
  with the exact next step. Determinism first, LLM to widen coverage — never to guess.

### 3c. Synthesize a grounded narrative (`llm_synthesis: true`)
Write the plain-English **"what happened & why"** — this is the RCA *description*, and
it's the other place you (the LLM) add value. It is **description only**: it summarizes
the already-concluded findings and never sets a verdict.

```python
from rca_engine.synthesize import build_narrative_context, set_narrative

ctx = build_narrative_context(result)   # factual view: verdict counts, clusters,
                                         # per-table findings (category/verdict/confidence/
                                         # rationale/drift/top-evidence). Facts only.
# ↳ YOU read `ctx` and write grounded prose. Lead with the systemic clusters (one fix,
#   many findings), then the genuine-data items to route, then anything needs-review.
#   Cite the numbers from ctx; do not invent causes beyond the concluded findings.
set_narrative(
    result,
    overall="This run surfaced N findings across M tables. The dominant issue is ...",
    per_table={"catalog.schema.fact_orders": "fact_orders: 9 findings trace to one ..."},
)
```

- The narrative renders as a clearly-labeled **🧠 Analyst summary** block (run-level in
  the TL;DR, per-table in each table notebook) — marked as *LLM synthesis, grounded in
  the evidence below*, so it's never mistaken for a verdict-setting fact.
- Ground every sentence in `ctx`: reference real counts, cluster signatures, drift
  magnitudes, and blast radius. If a fact isn't in `ctx`, don't assert it.

### 3d. Propose a fix for the gap cases (`suggest_fixes: true`)
The deterministic `generate_fixes` already attaches runnable fixes for the mechanical
categories (type/precision, timezone, trim/case, null/boolean, missing/extra rows) and
`validate_all_fixes` marks the ones a query proves close the gap. Two cases have **no
good template** because they need semantics: **`transpilation`** (rewrite the
mistranslated expression) and **`unknown`** residuals. This is where you (the LLM) write
the corrected Databricks SQL — grounded in the evidence bundle (declared `source_type`,
transpiled `target_derivation`, `transpile_issues`, sampled pairs, and the source/target
scripts) — and attach it **through the same validation gate**.

```python
from rca_engine.resolve import build_evidence_bundle, set_fix

for f in result.findings:
    top = f.top_hypothesis
    if top is None:
        continue
    # Only step in where the template can't help and no validated fix exists yet.
    if top.category.value in ("transpilation", "unknown") and not (top.fix and top.fix.validated):
        bundle = build_evidence_bundle(f, mapping=mapping,
                                       dialect=cfg.get("dialect", "snowflake"), runner=runner)
        # ↳ YOU write the corrected transform SQL from `bundle` (fix the mistranslated
        #   expr), plus a validation query returning a boolean `confirmed` (+ `n`) that
        #   checks the correction closes the gap on a sample.
        set_fix(
            f, runner,
            title="Rewrite mistranslated DATE_TRUNC to match source semantics",
            kind="fix_transpile", target="transform",
            sql="date_trunc('MONTH', `order_ts`)  -- corrected Databricks equivalent",
            rationale="Transpiler mapped the source truncation to the wrong unit.",
            validation_query=(
                f"SELECT (count(*) = sum(CASE WHEN date_trunc('MONTH', s.`order_ts`) = t.`{f.column}` "
                f"THEN 1 ELSE 0 END)) AS confirmed, count(*) AS n "
                f"FROM {f.source_table} s JOIN {f.target_table} t USING (id) "
                f"WHERE s.`{f.column}` <> t.`{f.column}`"
            ),
        )
```

- `set_fix` runs `validation_query` and marks the fix **✅ validated** only when it
  confirms; otherwise it's attached as an unvalidated suggestion. Never present an
  LLM-written fix as trusted without the query — same rule as verdicts.
- Prefer fixing the **transform** (so the migration is corrected at the source), not a
  one-off data patch, for `transpilation` cases.

### 4. Produce the RCA notebook + conclusion
- `write_rca_bundle(result, out_dir, recon_id)` writes a self-contained
  **`rca_<recon_id>/`** folder (one per run): a `00_index.ipynb` landing page, a
  shareable **`SUMMARY.md`** (paste into a ticket/Slack/email), the findings JSON,
  and **one notebook per reconciled table**. Each table notebook is symbol-coded and
  structured to mirror Lakebridge:
  1. **🧭 RCA Summary** — verdict counts (with meaning) for the whole `recon_id`,
     plus a **🔺 Top priorities** table (highest **severity** first — impact-ranked by
     verdict × blast radius × confidence, not just confidence). When `llm_synthesis`
     ran, a labeled **🧠 Analyst summary** (grounded narrative) sits right below it.
  2. **🧨 Systemic root causes** — findings that share one mechanism collapsed into a
     single "fix this, resolve N" row (skipped when nothing clusters).
  3. **📋 Reconciliation overview** — one row per table pair showing schema,
     row-level (missing in target / extra in target), mismatched columns, and a
     verdict rollup — the same breakdown Lakebridge reports.
  4. **📈 Match rates** — overall **row-level** and **column-level match %** for
     *every* table pair (including clean ones), not just the issues.
  5. **💥 Downstream blast radius** — affected tables and the consumers they propagate
     to (present when UC lineage is available).
  5b. **🛠️ Suggested fixes** — runnable remediations rolled up; each also appears as a
     review-then-run fix cell under its finding.
  6. **📅 Validation (date-range filterable)** — `dbutils.widgets` for
     `start_date`/`end_date` plus `validate_rows()` / `validate_column()` helpers
     and per-table calls, so the user can re-check row/column match % for any window.
  7. **🎯 Findings by verdict** — action tables (what to fix vs route).
  8. **🔬 Findings & evidence** — grouped by table pair, ordered schema → row-level
     → column-level; each finding has category/confidence/owner, root cause, fix,
     the confirming query + its evidence (including the **distribution-drift** line),
     and sample diffs.
  9. **🧾 Conclusion & recommended actions** — grouped by owner.
- The markdown is rendered from the concluded result, so every verdict is already
  backed by an executed drill-down query, and per-column counts are reconciled to
  the exact number of differing rows (recon `details` only stores a sample).
- **Per-table by default (multi-table recon):** `write_rca_bundle` emits one
  notebook per reconciled table inside `rca_<recon_id>/`, plus a `00_index.ipynb`
  that links each table to its verdict rollup — so each table routes to its owner
  independently. Set `combined_notebook: true` (config) or `combined=True` to also
  write a single-scroll `rca_<recon_id>_all.ipynb` where each table is a top-level
  section (`## 📦 <table>`). `scripts/run_rca.py` does all of this for you.
- **Recon customization is respected:** if the Lakebridge reconcile config uses
  `column_mapping`, `transformations`, `column_thresholds`, `table_thresholds`,
  `filters`, or `select/drop_columns`, the engine ingests them and adds
  `recon_config` evidence to the affected finding (e.g. "compared despite rename",
  "mismatch exceeds the ±0.005 tolerance"). See `migration/recon/README.md`.

### 5. Confirm with the user, then run all cells
- After writing the notebooks, **pause and ask the user for approval** before
  executing them. Show the TL;DR and the actual saved folder, then ask explicitly, e.g.:
  _"The RCA is generated at `<out_dir>/rca_<recon_id>/` (open `00_index.ipynb`). Are
  the findings and proposed fixes acceptable? Reply **yes** to run all cells, or tell
  me what to adjust."_
- **Do not run the notebooks until the user confirms.** If they request changes
  (reclassify a finding, add a drill-down, tweak a fix/owner), apply them, regenerate
  the bundle, and ask again.
- **On approval, run all cells** top-to-bottom so every confirming query executes
  live and the outputs are captured in the notebook.

### 6. Reconcile the conclusion with the executed outputs (always)
After running all cells, **read each query's output and check it still supports the
written verdict/confidence in that finding's markdown** (and the TL;DR + Conclusion
sections):
- If an output matches the stated conclusion, leave it.
- If an output changed the picture (e.g. offset is no longer constant, source is
  actually populated, extra rows are duplicates not new keys), **update that
  finding** (verdict, confidence, rationale, owner) and **regenerate the bundle**
  (`write_rca_bundle`) so the TL;DR and 🧾 Conclusion always match the evidence.
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
- **Two-tier discipline:** the deterministic engine is the first pass; use your LLM
  reasoning (step 3b) only on `unresolved_findings(result)`, and always via
  `resolve_finding` so the verdict is promoted only when a live query confirms it.
  The LLM widens coverage on the long tail — it must never override or bypass the
  query-confirmation gate.

## Audit trail

Every reconcile and RCA step appends one row to an append-only Delta table
(`audit_table` in `config.yml`, default `<recon_catalog>.<recon_schema>.rca_genie_audit`;
set to `off` to disable). The `reconcile`/`run`/`reconcile_and_run` helpers do this for
you — a reconcile row (pairs ok/error, schemas) and an RCA row (tables, diffs, findings,
notebook path) share a `run_id` so a full pipeline groups together. It records what ran,
when, by whom (`current_user()`), and the outcome. Writing is **best-effort**: if the
table can't be created/written (permissions), the step logs a note and continues — the
RCA itself is never blocked. The runner needs `CREATE TABLE` + `MODIFY` on the schema
(the table is auto-created on first write).

## Examples

**Example 0 — reconcile tables, then RCA (no recon_id yet)**
- User: _"Reconcile `mig_source_sim` against `mig_target` for `dim_customer` and
  `fact_orders`, then tell me what broke."_
- You: `reconcile_and_run(spark, "mig_source_sim", "mig_target", ["dim_customer",
  {"source": "fact_orders", "join_keys": ["order_id"]}])`. It auto-detects the
  `dim_customer` key, writes a fresh `recon_id`, then runs the full RCA on it (print
  the new `recon_id` so the user can re-run RCA on it later), then ask for approval.

**Example 1 — full run from a recon id**
- User: _"Run an RCA on Lakebridge reconcile `recon_id=0fe6...b747bf`."_
- You: load `config.yml`, `run(recon_id, spark)`, print the TL;DR, save the bundle
  under `/Workspace/Users/<user>/rca_notebooks/rca_<recon_id>/`, then ask for
  approval. On "yes", run all cells and reconcile. Expected shape of the answer:
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
