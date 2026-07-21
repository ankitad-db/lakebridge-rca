# One-Pager 1 — Current Project: The "As-Is" Blueprint

**Asset:** RCA Genie-Code Skill for Migration Reconciliation (`rca-recon`)
**Status:** Working accelerator, validated on a realistic Snowflake→Databricks test bed
**Owner:** _[team / DRI]_ · **Date:** _[date]_

---

## 1. What it is (in one line)
Lakebridge reconcile tells you **what** differs after a migration; this skill tells you
**why** — and whether each difference is a **migration defect** to fix or a **genuine data
difference** to route to the data owner — as a live, evidence-backed RCA notebook generated
inside Databricks Genie Code from a single `recon_id`.

## 2. What has been built
- **Genie Code skill (`rca-recon`)** — runs live in the Databricks workspace. Input: one
  `recon_id`. Output: a symbol-coded RCA notebook + machine-readable JSON.
- **Deterministic RCA engine (`rca_engine`)**, vendored inside the skill (no external install):
  - **Ingest** — reads Lakebridge recon output (`main`/`metrics`/`details`) into normalized
    findings + per-table summaries.
  - **Probes** — numeric, temporal, string, null/boolean, semi-structured value-difference detectors.
  - **Knowledge base** — per-dialect Snowflake→Databricks semantic differences (`snowflake.yaml`).
  - **Classifier** — maps signals → **category** (12) + **verdict** (4) + confidence.
  - **Code-aware correlation** — parses Lakebridge transpile output, recon config, and source DDL
    (via `sqlglot`) to confirm the cause from the actual translated code, not just the data.
  - **UC lineage (optional)** — column/table lineage as an independent provenance source.
  - **Live drill-down** — executes a confirmation query per finding against the real
    source/target tables and finalizes the verdict/confidence.
  - **Report** — TL;DR, Lakebridge-aligned per-table overview, row & column match rates,
    date-range validation widgets, findings + evidence, conclusion grouped by owner.
- **Human-in-the-loop** — approval gate before the notebook auto-runs all cells; conclusions are
  reconciled against executed outputs so the narrative can never contradict the evidence.
- **Cross-confirmation** — each finding cites up to **5 independent sources**: recon data + target
  code + source types + UC lineage + a live query ("Inputs used" per finding).
- **Migration test bed** — realistic retail warehouse: medallion pipeline (bronze/silver/gold),
  simulated Snowflake source, target DDL, incremental merge with watermark, Databricks Asset Bundle.
- **Conformance + tests** — 22 ground-truth scenarios (`scenarios.yaml`), 55 deterministic pytest
  cases, and an integration harness that checks live RCA output against the oracle.

## 3. Value baselines
_Illustrative estimates from the test bed pending a customer pilot; "How measured" defines the
metric so pilots can drop in real numbers._

| Dimension | Manual RCA (baseline) | With accelerator | How measured |
|---|---|---|---|
| **Latency** (recon → signed-off RCA) | ~1–3 days | **< 30 min** _(est.)_ | wall-clock, recon completion → final verdicts |
| **Throughput** (findings triaged) | ~2–5 / analyst-hour | **whole recon in one run** (10s–100s of findings) | findings ÷ runtime |
| **Coverage** (root-cause categories) | ad hoc, analyst-dependent | **12 categories, 22 conformance scenarios** | oracle (`scenarios.yaml`) |
| **Variance** (verdict consistency) | high (differs by analyst) | **deterministic** (same inputs → same result) | re-run determinism |
| **Evidence quality** | narrative, often uncited | **100% findings cite an executed query** + up to 5 sources | report audit |
| **Misattribution** (migration vs genuine) | common | **guarded** (source-NULL, generated-column, sentinel rules) | vs oracle verdicts |
| **Test confidence** | manual spot checks | **55 unit tests + integration harness** | CI pass rate |

> Baselines to be confirmed in the first pilot; replace _(est.)_ figures with measured values.

## 4. Local infrastructure anchors (what is currently workspace-specific)
These are the couplings to remove for the global asset (see One-Pager 2):
- **Fixed catalog/schemas** — `fevm_ps_dr_us_east_2_catalog`, `mig_source_sim` / `mig_target` /
  `reconcile`; schema-based namespacing (catalog creation needs a managed location here).
- **Fixed warehouse/profile** — `warehouse_id` + CLI profile `ps-dr-east` in `config.yml`.
- **Source simulated as a schema** — Snowflake stand-in rather than live Lakehouse Federation.
- **Dialect defaulted to Snowflake** — single KB (`snowflake.yaml`) wired as default.
- **Skill sync path** — vendored + imported to `/Users/<me>/.assistant/skills/rca-recon`.

## 5. Known edge cases discovered during testing
- **Lakebridge `_null_recon_` sentinel** for NULLs in `details` — engine treats it as NULL.
- **Sampled `details`** — per-column counts reconciled to the exact differing-row count via drill-down.
- **Generated/derived target columns** (e.g. fabricated `loyalty_tier`) can never equal source →
  flagged **needs-review**, not "genuine data".
- **Non-constant timezone offset** must not be read as a clean tz normalization → needs-review.
- **Date-only week-start vs timezone** ambiguity → classified as `env_config` (bucketing), not tz.
- **NULL vs sentinel** (`-1`, `N/A`) is a migration encoding choice, not a genuine data gap.
- **Integer overflow** (`NUMBER(38,0)`→`INT` 32-bit wrap) detected explicitly.
- **Unicode NFC vs NFD**, trailing whitespace, case — string-format normalization on load.
- **Aggregate/derived tables** have no 1:1 source row → compare at the aggregated grain.
- **Missing join keys** → fall back to grouped/`LIMIT` inspection at lower confidence.
- **Tooling constraints** — Snowflake transpiler (Morpheus) needs Java 21/Maven; and workspace
  blocks `pip install` from a URL → RCA **consumes** Lakebridge transpile output and the engine is
  **vendored** in the skill.

## 6. Bottom line
A working, evidence-first RCA accelerator that turns a reconciliation `recon_id` into a
signed-off root-cause report in minutes, with deterministic verdicts and a full test harness —
ready to be generalized into a plug-and-play global asset (One-Pager 2).
