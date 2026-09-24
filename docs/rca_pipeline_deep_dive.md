# ReconResolve — the RCA pipeline, explained end to end

This document explains **everything the engine does**, step by step, using the same 12 stages
shown in the interactive explorer (`docs/rca_tool_explorer.html`). Read it top to bottom and you
should understand what each stage does, how it does it, which files implement it, and how the
stages fit together into one run.

---

## 1. What the repo does (in one paragraph)

When you migrate an EDW (Snowflake, Oracle, Teradata, MSSQL, Synapse) to Databricks, **Lakebridge
reconcile** tells you *which* columns and rows differ between source and target. It does **not**
tell you *why*, or whether a difference is a **migration defect** or a **genuine data change**.
ReconResolve is the layer that sits after reconcile and answers *why*: it ingests the reconcile
output, classifies each difference, **confirms every verdict with an executed SQL query**, traces
the difference back through Unity Catalog lineage to the layer where it actually entered, clusters
related findings, proposes runnable fixes, and renders a reviewer-ready RCA notebook — all with an
audit trail.

### The core philosophy — deterministic-first, agentic-fallback, query-gated

- **Tier 1 (deterministic):** repeatable probes + a per-dialect knowledge base classify the
  *known* mismatch mechanisms and confirm them with templated live queries. No LLM.
- **Tier 2 (agentic / LLM fallback):** only the residual findings the probes *can't* fingerprint
  are handed to an LLM (Genie Code interactively, or a Foundation Model endpoint headless). The
  LLM proposes a cause **and a confirming SQL query**.
- **The gate is always the query.** A verdict — deterministic or LLM — is only trusted when an
  executed query confirms it. The LLM widens *coverage*; it never sets a verdict on opinion.

---

## 1a. What Lakebridge output we leverage

ReconResolve sits *after* Lakebridge and consumes two kinds of Lakebridge output.

### Reconcile output — the primary input (always used)

Lakebridge reconcile writes three Delta tables under `<recon_catalog>.<recon_schema>`, one set per
`recon_id`. Stage 2 (`rca_engine/ingest.py`) reads all three:

| Table | What Lakebridge puts there | What we read from it |
|---|---|---|
| **`main`** | one row per reconciled table pair | `recon_table_id`, `source_table`, `target_table` (fully-qualified) → the pairs to analyze |
| **`metrics`** | authoritative counts per pair | `source_record_count`, `target_record_count`, `row_comparison.missing_in_source/target`, `column_comparison.absolute_mismatch` + `mismatch_columns`, `schema_comparison` → **which** columns/rows mismatched + the match-rate scorecard |
| **`details`** | row-level samples by `recon_type` | `mismatch` rows (`<col>_base` = source, `<col>_compare` = target, `<col>_match`, plus join keys), `missing_in_source/target` rows, `schema` diffs → the **sample values the probes and drill-down run on** |

`metrics` is the source of truth for *what* differs; `details` supplies evidence samples; `main`
gives the pairs. The app-native reconciler (stage 1) writes this **exact same schema**, so
everything downstream is identical whether the recon came from real Lakebridge or from the app.

### Transpile output — optional, for code-aware RCA (stage 3b)

For *"this line of SQL did it"* evidence, we additionally leverage Lakebridge's **transpile**
artifacts (parsed by `rca_engine/lakebridge.py` with sqlglot):

- **`transpiled_output_dir`** — the transpiled **Databricks SQL** (target scripts) → per-column
  derivations (`cast(amount AS DECIMAL(18,2))`, …).
- **`transpile_error_file`** — Lakebridge's transpile **error/warning report** → surfaced against
  the affected columns.
- **`recon_config_path`** — the Lakebridge **reconcile config JSON** (join keys, column mappings,
  comparison transforms, thresholds) → reflected as evidence.
- **`source_scripts_dir`** — your original-dialect **source DDL** (declared types e.g.
  `NUMBER(18,4)`, `TIMESTAMP_LTZ`) — the code-aware counterpart to the transpiled target.

Without the transpile artifacts the engine still runs fully on just `main`/`metrics`/`details`; the
code-aware layer is purely additive and only upgrades verdicts from *"values differ"* to *"this
transform caused it."*

---

## 2. The pipeline at a glance

```
                 ENTRY POINTS (choose one)
   ┌──────────────┬──────────────────┬───────────────┐
   │ Genie Code   │ Databricks App   │ Local CLI     │
   │ skill        │ (React+FastAPI)  │ python -m …   │
   └──────┬───────┴────────┬─────────┴───────┬───────┘
          └────────────────┴─────────────────┘
                           │  (a recon_id — or table pairs to reconcile first)
   ┌───────────────────────▼───────────────────────────────────────────┐
   │ 1  Reconcile (optional)   compare source↔target → recon_id          │
   │ 2  Ingest                 recon main/metrics/details → Findings     │
   │ 3  Classify               probes + dialect KB → ranked hypotheses   │
   │ 3b Code-aware (optional)  sqlglot reads source & target SQL         │
   │ 4  Live drill-down        confirm each hypothesis on real rows      │
   │ 5  Distribution drift     null-rate / cardinality / numeric shift   │
   │ 6  UC lineage trace-back  walk upstream to the root layer           │
   │ 7  Downstream blast-radius who consumes the affected table?         │
   │ 8  Systemic clustering    fix one, resolve many                     │
   │ 9  Fix + validation gate  runnable remediation, dry-run confirmed   │
   │ 10 LLM Tier-2 fallback    residual only: hypothesis + confirm query │
   │ 11 Learning-loop memory   remember confirmed causes for next time   │
   │ 12 Outputs + audit        notebook · JSON · SUMMARY.md · audit row  │
   └────────────────────────────────────────────────────────────────────┘
```

| # | Stage | Tier | Live queries? | Implemented in |
|---|-------|------|:---:|----------------|
| 1 | Reconcile (optional) | input | ✅ | `rca_engine/reconcile.py` |
| 2 | Ingest | deterministic | — | `rca_engine/ingest.py`, `models.py` |
| 3 | Classify (probes + KB) | deterministic | — | `rca_engine/classify.py`, `probes/`, `knowledge/` |
| 3b | Code-aware correlation | deterministic | — | `rca_engine/lakebridge.py` (+ a manifest) |
| 4 | Live drill-down | deterministic | ✅ | `rca_engine/drilldown.py`, `scan.py` |
| 5 | Distribution drift | deterministic | ✅ | `rca_engine/drift.py` |
| 6 | UC lineage trace-back | deterministic | ✅ | `rca_engine/lineage.py` |
| 7 | Downstream blast-radius | deterministic | ✅ | `rca_engine/lineage.py` |
| 8 | Systemic clustering | deterministic | — | `rca_engine/cluster.py` |
| 9 | Fix + validation gate | deterministic | ✅ | `rca_engine/fixgen.py` |
| 10 | LLM Tier-2 fallback | agentic | ✅ | `rca_engine/resolve.py`, `synthesize.py`, `llm_fallback.py` |
| 11 | Learning-loop memory | deterministic | ✅ | `rca_engine/memory.py` |
| 12 | Outputs + audit | deterministic | — | `rca_engine/report.py`, `audit.py` |

> **Note on ordering.** Stages 2–9 (plus the *apply* side of 11) run inside one function,
> `rca_engine/analyze.py::analyze()`. Its real execution order is: ingest → classify (incl. 3b) →
> apply memory prior → drill-down → drift → lineage → blast-radius → fixes+validate → **clustering
> last**. Stage 10 (LLM fallback), the *record* side of stage 11, and stage 12 (report + audit) are
> orchestrated by the entry point *around* `analyze()`. The numbering above is the logical
> narrative order used in the explorer.

---

## 3. Entry points — how a run starts

All three drive the **same** `rca_engine`. They differ only in *who* calls it and *where* the LLM
tier comes from.

- **Genie Code skill** (`skill/rca-recon/SKILL.md`, `scripts/run_rca.py`, `config.yml`) — the
  in-workspace agent reads `SKILL.md`, runs the vendored engine inside a Databricks notebook
  (Spark session), and *is itself* the Tier-2 LLM (interactive, agentic).
- **Databricks App** (`app/server/rca_service.py`, `routes/api.py`, `llm_fallback.py`) — a
  React+FastAPI app to trigger reconciliation, browse runs, run full/single-table RCA, and view
  the audit trail. Tier-2 uses the Foundation Model API.
- **Local CLI** (`rca_engine/cli.py`) — the same engine from a terminal (CI, scripted validation).
  Deterministic by default; pass `--endpoint <model>` to enable Tier-2 (see stage 10).

---

## 4. The data model (so the stages make sense)

Defined in `rca_engine/models.py`. Every stage reads/writes these:

- **`Finding`** — one problem: a mismatched column, a set of missing/extra rows, or a schema diff.
  Carries `recon_id`, `source_table`, `target_table`, `recon_type`, `column`, `mismatch_count`,
  `total_count`, `samples`, `hypotheses`, and `metadata`. `finding.top_hypothesis` is the
  highest-confidence hypothesis.
- **`ReconType`** — `COLUMN_MISMATCH` · `MISSING_IN_TARGET` · `MISSING_IN_SOURCE` · `SCHEMA`.
- **`MismatchSample`** — one sampled row: the join `keys`, the `column`, and `source_value` /
  `target_value`.
- **`Hypothesis`** — a candidate explanation: `category`, `verdict`, `confidence`, `rationale`,
  `remediation`, `recommended_owner`, a list of `evidence`, and an optional `fix`.
- **`RootCauseCategory`** — `type_precision` · `timezone` · `string_format` · `null_boolean` ·
  `semi_structured` · `volume_missing` · `volume_extra` · `transpilation` · `upstream_drift` ·
  `env_config` · `recon_config` · `unknown`.
- **`Verdict`** — `migration_induced` (🔧 fix in the migration) · `genuine_data` (📊 route to the
  data owner) · `benign` (✅ no action) · `needs_review` (🔍 investigate).
- **`Evidence`** — one fact: a `label` (`probe`/`drilldown`/`code`/`transpile`/`drift`/`lineage`/
  `llm_drilldown`/`memory`/`fix`…), a human `detail`, an optional executed `query`, and structured
  `data` (which may contain `confirmed: true`).
- **`Fix`** — a runnable remediation: `title`, `kind`, `sql`, `target`, `confidence`,
  `validation_query`, and `validated`.
- **`TableSummary`** — per-table scorecard: counts, `mismatch_columns`, `join_keys`, `date_column`,
  `row_match_pct`, `downstream_tables`, and an optional `narrative`.
- **`RootCauseCluster`** — a systemic cause shared by many findings: `category`, `verdict`,
  `signature`, `members` (`table.column`), `tables`, `finding_count`, `rows_impacted`.
- **`RcaResult`** — the whole run: `recon_id`, `dialect`, `findings`, `table_summaries`,
  `clusters`, and an optional LLM `narrative`.

---

## 5. The stages, in detail

### Stage 1 — Reconcile (optional) · `rca_engine/reconcile.py`

**Purpose.** Produce a `recon_id` when you don't already have one, without needing the Lakebridge
CLI/Spark job — the app-native reconciler compares source↔target directly on a SQL warehouse.

**What it does.** For each `TablePairSpec` (source table, target table, optional join keys / column
mapping):
1. **Join-key detection** — if you don't provide keys, `detect_join_keys` tries id-like candidates
   in order (`id`, `<table>_id`, any `*_id`, all id-like columns together, then id-like + a date
   column for grain keys), capped at `max_key_tries`, and accepts the first that is **unique +
   non-null** on the source.
2. **Schema compare** — base-type diffs and one-sided/renamed columns are reported as schema diffs
   (via `column_mapping`) instead of aborting the run (Lakebridge's `report_type=all` failure mode).
3. **Counts + column mismatches** — `LEFT ANTI JOIN` for missing rows each way; a single aggregate
   with `count_if(NOT (s.col <=> t.col))` per comparable column; sampled mismatch rows (capped by
   `sample_limit`, default 100).
4. **Persist** — writes Lakebridge-compatible `main` / `metrics` / `details` rows under a fresh
   `recon_id` in `<catalog>.<recon_schema>`, so the output is identical to what real Lakebridge
   produces and flows into the same downstream stages.

**Guardrail.** Each pair is isolated — a missing table / undetectable key / query error marks that
pair `error` and the run continues.

**Output.** A `ReconRunResult` with one `recon_id` covering all pairs.

---

### Stage 2 — Ingest · `rca_engine/ingest.py`

**Purpose.** Normalize any reconcile output (Lakebridge or app-native) into `Finding` objects.

**What it does.** For one `recon_id`, `ingest_with_summaries()` reads the three reconcile tables:
- **`main`** → the table pairs (fully-qualified source/target names).
- **`metrics`** → the source of truth for counts and *which* columns mismatched
  (`source_record_count`, `target_record_count`, `row_comparison.missing_in_*`,
  `column_comparison.absolute_mismatch`, `mismatch_columns`, `schema_comparison`).
- **`details`** → row-level samples used as evidence and probe inputs. Mismatch rows expose
  `<col>_base` (source), `<col>_compare` (target), `<col>_match`, plus the join keys.

It emits **one `Finding` per mismatched column**, one per missing-in-target / missing-in-source set,
and one per schema diff — and a `TableSummary` for **every** pair (clean or not), guessing the
date column for later date-range validation. `only_table` restricts to a single pair (the app's
one-table-at-a-time flow).

**Output.** `(list[Finding], list[TableSummary])`.

---

### Stage 3 — Classify (probes + KB) · `rca_engine/classify.py`, `probes/`, `knowledge/`

**Purpose.** The deterministic heart. Turn raw value differences into **ranked hypotheses** with a
category, confidence, and remediation — no LLM.

**What it does.**
- For each column-mismatch finding, it runs **all probes** (`rca_engine/probes/run_all`) over every
  sampled `(source_value, target_value)` pair. Each probe returns `ProbeSignal`s (category,
  `strength ∈ [0,1]`, detail, `meta`, semantic `kind`). Probe families:
  - `numeric` — scale/precision loss, rounding, unit factors.
  - `temporal` — constant timezone offsets, precision truncation.
  - `string` — case/trim/collation/encoding differences.
  - `nullbool` — NULL handling & boolean encodings (Y/N ↔ true/false).
  - `complex` — VARIANT/JSON representation (key order, nested types).
- Signals are aggregated per category; **confidence** = mean strength × (0.5 + 0.5 × coverage),
  where coverage is the fraction of samples that fired.
- The **knowledge base** for the source dialect (`rca_engine/knowledge/<dialect>.yaml` via
  `load_kb`) supplies the remediation text and dialect-specific function-translation facts.
- A default **verdict** is assigned by category (`_verdict_for`): migration categories →
  `migration_induced` above a strength threshold else `needs_review`; `upstream_drift` →
  `genuine_data`; `semi_structured` → `benign` when confident; nothing fired → `unknown` /
  `needs_review`.
- Missing/extra rows → `volume_missing` / `volume_extra`; schema diffs → `type_precision`.
- A **freshness pass** marks a table's *unexplained, partial* column mismatches as likely
  `upstream_drift` when the table already shows snapshot/load-time drift (confirmed later by the
  drill-down).

**Output.** Each finding now has `hypotheses` sorted by confidence, each with probe `evidence`.

---

### Stage 3b — Code-aware correlation (optional) · `rca_engine/lakebridge.py`

**Purpose.** Turn *"the values differ"* into *"this line of SQL did it."* Only runs when you supply
code (see the config keys under "Code-aware RCA").

**What it does.** `build_mapping()` uses **sqlglot** to parse the **source** (original-dialect) and
**target** (migrated Databricks) scripts you provide — via a per-table `table_manifest.yml`, or a
transpiled-output folder + source-scripts folder, and/or a Lakebridge recon-config JSON and
transpile-error file. For each target column it derives the exact transform expression, its
functions, and whether it's a direct passthrough. Then `classify.py::_code_correlation_pass`
overlays this onto findings:
- Adds the **target derivation** as `code` evidence (e.g. `cast(amount AS DECIMAL(18,2))`,
  `round(gross_amount*1.08,2)`) and raises confidence.
- A **direct passthrough** *rules out* transpilation (the diff is precision/upstream).
- A **generated** column (target value not carried from the same-named source column) is flagged
  `needs_review` — it can never match source (audit/derived column vs defect — a human decides).
- Reflects **recon-config** customizations (column renames, comparison transforms, tolerances) and
  **declared source types** (e.g. `NUMBER(18,4)`, `TIMESTAMP_LTZ`) as corroborating evidence.
- A load `WHERE` filter in the transform explains missing-in-target rows.

---

### Stage 4 — Live drill-down · `rca_engine/drilldown.py`, `scan.py`

**Purpose.** The step that makes verdicts *earned*: confirm each hypothesis with a real query.

**What it does.** For every finding, `run_drilldown()` issues a **category-specific** confirming
query joined on the learned keys and returns an `Evidence` line with `data.confirmed`:
- `timezone` → is there a **single distinct** `target − source` offset? (constant offset ⇒ tz).
- `type_precision` / `transpilation` → do values become equal after **rounding to 2 dp**? max/avg
  abs diff.
- `string_format` → are the diffs **trim/lower**-only?
- `null_boolean` → how many differing rows **involve a NULL**.
- `upstream_drift` → is the source genuinely NULL / how many rows differ (route to data owner).
- volume → **watermark** check (target `max(key)` < source `max(key)`) or extra-rows anti-join.

On confirmation, confidence is bumped and a `needs_review` finding is **promoted** to a concluded
verdict (migration_induced, or genuine_data for drift) — unless the code pass flagged the column as
*generated*, in which case it stays `needs_review` for a human. **Scan scoping** (`scan.py`) bounds
these joins to the reconciliation-flagged keys and/or a partition window so they don't full-scan
huge tables. Every drill-down is defensive: a failed query leaves the deterministic verdict intact.

---

### Stage 5 — Distribution drift · `rca_engine/drift.py`

**Purpose.** Add the missing *magnitude* to sharpen migration-vs-genuine.

**What it does.** For each column-level finding it measures the **source vs target** distribution in
one query: row counts, null-rate, cardinality (`approx_count_distinct`), and — for numerics —
min/max/mean/stddev. A **stable** distribution (null-rate and cardinality steady) points to a
representation/precision change (migration); a **material shift** (null-rate moves > 1pp, or NDV
changes > 5%) points to a genuine upstream population change. It attaches a `drift` evidence line
and structured `metadata['drift']`. It never sets a verdict — it annotates.

---

### Stage 6 — UC lineage trace-back · `rca_engine/lineage.py`

**Purpose.** Point at the layer where the difference *actually entered*, not just the reconciled
table. Optional; enable with `use_uc_lineage`.

**What it does.** `run_lineage()` reads `system.access.column_lineage` (then `table_lineage`) and,
for each finding, walks upstream **hop by hop** with `trace_upstream()`:
- **Column-scoped** when a column is known — it follows *that column's* parents only. This is what
  gives **sibling isolation**: a finding on `leaf_e.amount` walks `leaf_e ← branch_c ← shared_b ←
  raw_a` and never crosses into a sibling arm, so an unrelated defect on a sibling can't leak in.
- **Depth-agnostic** — it keeps walking to the roots (bounded by `max_lineage_hops`, default 10,
  and `max_paths`), so a defect injected N layers up is surfaced as a full path.
- Cycle-safe and query-cached (one parent lookup per node per run).

It attaches the immediate provenance, a **surprise check** (column sourced from an unexpected
table), and a readable multi-hop trace-back path. Fully defensive — no lineage ⇒ attaches nothing.

---

### Stage 7 — Downstream blast-radius · `rca_engine/lineage.py`

**Purpose.** Answer *"if I don't fix this, what else is wrong?"* — prioritize by propagation.

**What it does.** `run_blast_radius()` runs only for tables carrying an **actionable** finding
(`migration_induced` / `needs_review`). `fetch_downstream()` lists the tables that **consume** the
affected target (it's the *source* in table lineage). The downstream list is stored on the matching
`TableSummary` and added as an evidence line on the worst finding for that table.

---

### Stage 8 — Systemic clustering · `rca_engine/cluster.py`

**Purpose.** Collapse the long tail: *fix one thing, resolve many*.

**What it does.** `build_clusters()` groups findings that share **one mechanism** — a mistranslated
expression, one category concentrated in a table, or a shared upstream root — into a
`RootCauseCluster` (only groups with ≥ 2 members). The report then leads with the single fix that
clears the most findings. *(In code this runs last in `analyze()`, after fixes.)*

---

### Stage 9 — Fix + validation gate · `rca_engine/fixgen.py`

**Purpose.** Produce the *how* — a concrete, runnable remediation — and prove it closes the gap.

**What it does.** `generate_fixes()` attaches a deterministic `Fix` per category:
`type_precision` → widen the cast to the source scale; `timezone` → normalize to UTC on load;
`string_format` → align TRIM/case; `null_boolean` → explicit mapping; `volume_missing` → a
back-fill (`LEFT ANTI JOIN`) statement; `volume_extra` → a de-dupe (`row_number`) rewrite;
`semi_structured` → a recon-config normalization; `transpilation` → surface the derivation to
correct by hand. Then the **validation gate** (`validate_all_fixes`) dry-runs each fix's
`validation_query` and marks it **✅ validated** only when the query confirms the mechanism explains
the *entire* gap. Fixes are always **suggestions** — the engine attaches, a human runs.

---

### Stage 10 — LLM Tier-2 fallback (residual only) · `rca_engine/resolve.py`, `synthesize.py`, `llm_fallback.py`

**Purpose.** Widen coverage to the residual long tail the probes couldn't fingerprint — **without**
loosening the query-backed rule.

**What it does.**
- `unresolved_findings()` surfaces only residuals (`needs_review` / `unknown`).
- `build_evidence_bundle()` packages the facts for one finding: samples, declared source type, the
  migrated `target_derivation`, transpile issues, prior evidence, and the UC lineage **trace-back**.
- The LLM (Genie Code interactively, or a Foundation Model endpoint via `rca_engine/llm_fallback.py`
  / `app/server/llm_fallback.py`) proposes a `category`, `rationale`, and a **`confirm_query`** that
  returns a boolean `confirmed`.
- `resolve_finding()` **executes that query** and promotes the verdict **only if it confirms**;
  otherwise the finding stays `needs_review` with the proposal recorded as the next check.
- `set_fix()` lets the LLM propose a corrected-SQL fix for `transpilation`/`unknown`, validated by
  the same gate.
- `synthesize.py` lets the agent write a **grounded narrative** (`build_narrative_context` →
  `set_narrative`) — description only, clearly labeled as LLM synthesis, never a verdict.

**How it's invoked.** Interactive in Genie Code; in the App via the FM API; in the CLI via
`--endpoint <model>` (e.g. `databricks-claude-opus-5`). Omit the endpoint ⇒ deterministic only.

---

### Stage 11 — Learning-loop memory · `rca_engine/memory.py`

**Purpose.** Migrations repeat their mistakes — remember confirmed causes so recurring ones
auto-classify next time.

**What it does.**
- `record_confirmations()` writes a compact **signature → cause** row for every *query-confirmed*,
  concluded finding into an append-only Delta table.
- The **signature** is *mechanism-based, not column-specific* — `dialect | category | mechanism`,
  where mechanism is the translated function set (`fn:round,cast`), else a numeric scale delta
  (`scale:4->2`), else the recon type — so a cause learned on one column generalizes.
- `load_memory()` reads them back aggregated by signature; `apply_memory()` uses them as a **prior**
  *before* the drill-down: for a matching residual it proposes the remembered category (still gated
  by a query); for a matching known finding it nudges confidence and cites prior sightings.

**Guardrail.** Memory never finalizes a verdict — the drill-down or Tier-2 query still confirms.

---

### Stage 12 — Outputs + audit · `rca_engine/report.py`, `audit.py`

**Purpose.** The sign-off artifacts.

**What it does.** `write_rca_bundle()` writes a self-contained `rca_<recon_id>/` folder:
- **`<table>.ipynb`** — one reviewer-ready notebook per reconciled table. Each has a TL;DR
  (verdict counts, systemic causes, top priorities, per-table overview, match-rate scorecard,
  blast-radius, suggested-fixes roll-up), date-range **validation cells** (row & column match % with
  widgets), and a per-finding section: verdict + category + confidence + owner, the **executed
  query pre-filled to re-run**, sample diffs, the suggested-fix cell, an *Inputs used* provenance
  line, and a closing conclusion grouped by owner.
- **`00_index.ipynb`** — master routing notebook (multi-table runs), tables sorted by worst severity.
- **`SUMMARY.md`** — a shareable plain-markdown summary (paste into a ticket/Slack/email).
- **`rca_<recon_id>.json`** — the full machine-readable result.
- Optional single-scroll `rca_<recon_id>_all.ipynb` (`combined_notebook`).

`audit.py` appends one row per orchestration step (reconcile / rca / publish) to an append-only
Delta table — *what ran, when, by whom, on what, and the outcome* — shared by the app, skill, and
CLI. Best-effort: auditing never breaks the main flow.

---

## 6. How a verdict is decided (the gate)

1. A probe (or the KB, or code-aware evidence, or a memory prior, or an LLM proposal) suggests a
   **category**.
2. The category implies a **default verdict** (migration / genuine / benign / needs-review).
3. A **live query** must confirm it: the drill-down (Tier 1) or the LLM's `confirm_query` (Tier 2).
4. Confirmed ⇒ promoted to a concluded verdict with the executed query stored as evidence.
   Not confirmed ⇒ **stays `needs_review`** with the proposal recorded as the next check.

**Nothing is promoted on a probe or an LLM opinion alone.** That is the single invariant the whole
design protects.

---

## 7. Categories the engine recognizes

| Icon | Category | What it catches | How it's detected |
|---|---|---|---|
| 🔢 | `type_precision` | numeric scale/precision loss | values equal after rounding to N scales |
| 🕐 | `timezone` | constant time-offset shift | a single distinct known offset |
| 🔤 | `string_format` | case / trim / collation / encoding | equal after NFC + trim + case-fold |
| ✔️ | `null_boolean` | NULL handling & boolean mapping | NULL↔value and Y/N/1/0 ↔ true/false |
| 🧬 | `semi_structured` | VARIANT / JSON representation | parse JSON; compare keys/types, ignore formatting |
| ➖➕ | `volume_missing` / `volume_extra` | row-count losses & duplicates | anti-join on keys; source-only / target-only / dup |
| 🔧 | `transpilation` | function-translation differences | known function diffs from the dialect KB |
| 📊 | `upstream_drift` | genuine distribution change | null-rate / cardinality / numeric shift |

---

## 8. Configuration reference (grounded in `skill/rca-recon/config.yml`)

- **Location & output** — `recon_catalog`, `recon_schema`, `warehouse_id`, `output_dir`
  (bare name → workspace home; absolute path → used as-is; supports `/Workspace/…`, `/Volumes/…`),
  `combined_notebook`.
- **Source dialect** — `dialect` (`snowflake` | `oracle` | `teradata` | `mssql` | `synapse`;
  unknown dialects still run on generic probes), `source_schema`, `target_schema` (for stage 1).
- **Code-aware RCA (stage 3b)** — `recon_config_path`, `transpiled_output_dir`,
  `source_scripts_dir`, `transpile_error_file`, or the most robust `tables:` manifest
  (`{target, source, source_script, target_script, join_keys[], date_column}`).
- **Lineage & blast-radius (stages 6–7)** — `use_uc_lineage`, `max_lineage_hops` (default 10),
  `blast_radius` (defaults to `use_uc_lineage`).
- **Drift & scan scoping (stage 5 / 4)** — `distribution_drift`, plus scan-scope knobs that bound
  live queries to flagged keys and/or a partition window.

---

## 9. The same engine, three surfaces

| Stage | Genie Code skill | Databricks App | Local CLI |
|---|:---:|:---:|:---:|
| 1 Reconcile | ✅ (or Lakebridge) | ✅ (trigger UI) | ✅ (or supply `recon_id`) |
| 2–9 deterministic | ✅ | ✅ | ✅ |
| 10 LLM Tier-2 | ✅ (Genie is the LLM, agentic) | ✅ (FM API) | ✅ *only* with `--endpoint` |
| 11 Memory | ✅ | ✅ | ✅ |
| 12 Outputs + audit | ✅ notebook in workspace | ✅ dashboard + audit page | ✅ local `rca_<id>/` folder |

The deterministic stages (2–9, 11) are identical everywhere — the surfaces differ only in how a run
is triggered and where the Tier-2 LLM comes from.

---

## 10. A worked example — the deep-diamond run

Bed: `migration/demo_diamond_deep/` (see its README). Topology
`raw_a → shared_b → branch_c/branch_d → leaf_e/leaf_f → report_e/report_f`; the two leaves are
reconciled. One live run (`recon_id 1d04640331554f61874b47299b08f5b1`, 500 rows/leaf) exercises the
whole pipeline:

- **Stage 2** ingests 5 findings across 2 pairs.
- **Stage 3** fingerprints `amount` → `type_precision` and `sku` → `string_format`; `net_amount` →
  no probe match (`unknown`).
- **Stage 3b** cites the exact transforms (`cast(amount AS DECIMAL(18,2))`, `round(gross*1.08,2)`,
  `concat(lower(sku),'  ')`).
- **Stage 4** confirms the scale loss and the trim/case on real rows (Tier 1 verdicts).
- **Stage 6** traces every finding **3 hops** back to root `raw_a`; `leaf_e` never surfaces arm-D's
  `sku` (sibling isolation).
- **Stage 7** shows `leaf_e → report_e`, `leaf_f → report_f`.
- **Stage 8** clusters `amount` across both leaves into one `shared_b` root cause.
- **Stage 10** hands the two `net_amount` residuals to Claude, which proposes the tax-vs-discount
  hypothesis and a confirming query; promoted only when the query passes.
- **Stage 12** writes the per-table notebooks, index, SUMMARY.md, JSON, and an audit row.

---

*This document is a companion to the interactive explorer at `docs/rca_tool_explorer.html` — open
that to click through the same 12 stages with per-stage example output.*
