# M1 — Lakebridge Recon output analysis & RCA gap list

**Purpose.** Catalogue *everything* Lakebridge Recon writes, map what the ReconResolve
engine consumes today vs. ignores, and rank the gaps to close so the tool leverages all
Lakebridge output. This is the M1 gate deliverable; M2 dev is scoped from the gap list
below.

**Sources.** `~/Downloads/lakebridge-recon 2/{SKILL.md, configuration.md, data_model.md}`
and the Lakebridge docs (https://databrickslabs.github.io/lakebridge/docs/reconcile/).
Current engine: `rca_engine/ingest.py` (and `lakebridge.py`, `analyze.py`).

---

## 1. What Lakebridge Recon produces

Metadata schema (default `lakebridge.recon`; authoritative value in
`/Users/<user>/.lakebridge/reconcile.yml` → `metadata_config`). Two operations write here:
`reconcile` (rows/columns/schema) and `aggregates-reconcile` (per-rule aggregates).
`report_type` (`schema`/`row`/`data`/`all`) gates which metrics are populated.

| Table / view | Grain | Key columns | Engine today |
|---|---|---|---|
| `main` | per (recon_id, table) | `recon_id`, `recon_table_id`, **`source_type`** (dialect), `source_table`/`target_table` structs, **`report_type`**, **`operation_name`**, `start_ts`/`end_ts` | Reads only `recon_table_id`, `source_table`, `target_table`. **Ignores** dialect/report_type/operation/timestamps. |
| `metrics` | per recon_table_id | `recon_metrics{source_record_count, target_record_count, row_comparison{missing_in_source, missing_in_target}, column_comparison{absolute_mismatch, **threshold_mismatch**, mismatch_columns}, schema_comparison}`, **`run_metrics{status, run_by_user, exception_message}`** | Reads counts + `absolute_mismatch` + `mismatch_columns` + `schema_comparison`. **Ignores `threshold_mismatch` and all of `run_metrics` (status/exception).** |
| `details` | per sampled record (SAMPLE ~50–400) | **`record_key` VARIANT**, **`source_row` VARIANT**, **`target_row` VARIANT**, `mismatch_columns ARRAY<STRING>`, `recon_type` (`mismatch`/`missing_in_source`/`missing_in_target`/**`threshold_mismatch`**) | **BROKEN**: `ingest.py:187` does `SELECT recon_type, data …` — modern `details` has **no `data` column**. |
| `details_columns` (view) | per (record, column) | `column_name`, `source_value` STRING, `target_value` STRING, `is_mismatch` | **Unused** — this is the clean, pre-exploded per-column diff the engine should read. |
| `details_kv` (view) | legacy long k/v | `<col>_base`/`<col>_compare`/`<col>_match` + join keys | This is the *only* place the old map shape still exists — what `ingest.py` currently assumes. |
| `schema_details` | per compared column | `source_column`, `source_datatype`, `databricks_column`, `databricks_datatype`, `is_valid` | **Unused** — engine synthesizes schema findings from a `details` row-type `'schema'` that modern Lakebridge does not emit. |
| `recon_run_context` | per recon_id | `config` VARIANT = `{reconcile, table_recon}` — join_columns, column_mapping, transformations, column/table thresholds, filters, hash_expression_overrides, select/drop, aggregates, sampling | **Unused** — the full run *intent*. Today the engine needs separate `--recon-config`/artifacts to get any of this. |
| `aggregate_rules` | per rule | `rule_id`, `rule_type`, `rule_info{agg_type, agg_column, group_by_columns}` | **Unused** — no aggregate RCA. |
| `aggregate_metrics` | per (recon_table_id, rule) | `recon_metrics{mismatch, missing_in_source, missing_in_target}`, `run_metrics` | **Unused** |
| `aggregate_details` / `aggregate_details_columns` | per sampled agg record | record-level samples + `rule_id` | **Unused** |

---

## 2. Engine-consumed vs. ignored (grounded in `rca_engine/ingest.py`)

**Consumed today** (legacy assumptions):
- `main`: identity structs only (`ingest.py:143-153`).
- `metrics`: counts, `absolute_mismatch`, `mismatch_columns` (CSV), `schema_comparison` (`:158-184`).
- `details`: `SELECT recon_type, data` and a `data<array<map>>` with `<col>_base`/`_compare`/`_match` (`:186-191`, `_mismatch_samples :86-107`) — the **legacy** shape.
- Schema: expects a `details` row with `recon_type='schema'` + `is_valid` (`:234-244`).

**Ignored / incompatible:**
- Modern `details` VARIANT columns (`record_key`/`source_row`/`target_row`) and the `details_columns` view.
- `metrics.column_comparison.threshold_mismatch`; the whole `run_metrics` struct (`status`, `exception_message`).
- `schema_details` table; `recon_run_context.config`; every `aggregate_*` table.
- `main.source_type` (dialect is passed as a CLI flag, not read from the run).

---

## 3. Ranked gap list (what M2 must close)

| # | Gap | Severity | Fix (M2) |
|---|---|---|---|
| G1 | **Ingest reads a non-existent `data` column** on modern `details`; schema via a non-existent `details` row-type | **Blocker** — real runs won't ingest | Read `details_columns` (view) for per-column diffs + VARIANT `source_row`/`target_row` for row images; read `schema_details` for schema. Keep `details_kv`/`data<map>` as an auto-detected fallback so both shapes work. |
| G2 | **Errored run not detected** (`run_metrics.exception_message`) | High — RCA would "analyze" a run that actually failed to execute | New first-class result state: if `exception_message` non-empty, short-circuit with the error + config-based fix (bad filter/mapping/connection/hash override), don't classify diffs. |
| G3 | **`threshold_mismatch` unhandled** | High — within-tolerance diffs mis-verdicted | New recon_type; treat as benign/within-tolerance, cite the `column_thresholds` bound. |
| G4 | **`schema_details` unused** | High — schema/precision RCA weak | Drive type-precision / name-divergence findings from the structured table (`is_valid`, `source_datatype` vs `databricks_datatype`). |
| G5 | **`recon_run_context.config` unused** | High — needs external artifacts today | Auto-build the mapping (join_columns, column_mapping, transformations, thresholds, filters, hash overrides, aggregates) from `config` — feeds `build_mapping` with zero artifacts. |
| G6 | **No aggregates-reconcile RCA** | Medium — a whole Lakebridge operation unsupported | New `aggregate_rca` module: per-rule (MIN/MAX/SUM/COUNT/AVG…) mismatch classification + confirming query, joined `aggregate_rules`↔`aggregate_metrics`↔`aggregate_details`. |
| G7 | **Thresholds not verdict-aware** | Medium | Use `column_thresholds`/`table_thresholds` (from G5) to mark tolerated diffs benign and to explain small-delta numeric mismatches. |
| G8 | **Deep expression localization** (prior plan) | Medium | Depth-agnostic, catalog-DDL-sourced source-column/expression trace, on by default (fills "exact logic" when no transpiled artifacts). |
| G9 | **`main.source_type` not read** | Low | Read the dialect from the run to select the KB automatically (still overridable). |
| G10 | **Dialect coverage unverified** | Low/Med | Confirm KBs for all 7 dialects (`databricks, snowflake, oracle, mssql, synapse, redshift, teradata`); add missing per-dialect rules. |

---

## 4. Lakebridge signal → RCA feature coverage matrix

| Lakebridge signal | Enables RCA feature | Status |
|---|---|---|
| `run_metrics.exception_message` | Errored-run triage (distinct from "found diffs") | **New (G2)** |
| `column_comparison.threshold_mismatch` + `column_thresholds` | Within-tolerance/benign verdicts, small-delta explanation | **New (G3/G7)** |
| `schema_details` | Type-precision / schema-mismatch findings + fixes | **New (G4)** |
| `recon_run_context.config` | Config-driven join keys/mappings/transforms/filters/hash — no artifacts | **New (G5)** |
| `aggregate_*` | Aggregate-reconcile RCA | **New (G6)** |
| `details_columns` / VARIANT rows | Correct per-column + row-image samples (all recon_types) | **Fix (G1)** |
| `hash_expression_overrides` (config) | Explain "all/most rows mismatch" | **New (via G5)** |
| `main.source_type` | Auto dialect / KB selection | **New (G9)** |
| target code / catalog DDL / job SQL / UC lineage | transpilation & upstream localization (existing + `trace_job` + G8) | Existing + **New (G8)** |

---

## 5. Notes carried into M2/M3
- `details` is a **sample**; always use `metrics` for true counts (already respected).
- VARIANT columns must be read Spark-side with `to_json(...)`/`:` accessors — the
  `SparkQueryRunner` path handles this; the local Statement-API path must `to_json` in SQL.
- All new passes stay **deterministic + best-effort** (attach nothing on absence/error),
  matching the existing `run_lineage`/`run_mismatch_trace` contract, and are **mirrored**
  to `app/rca_engine` + `skill/rca-recon/rca_engine` (CI `diff -rq` parity).
- M3 will confirm the real metadata schema + which dialect source(s) are actually connected
  on `ps-dr-east` (drives real-run vs. fixture coverage for the all-dialects demo).
