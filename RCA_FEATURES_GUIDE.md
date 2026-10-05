# ReconResolve — Features Guide (for Ankita)

*A plain-English walkthrough of everything the RCA tool does. This is your personal
reference — it lives in your local working copy, not the shared repo.*

---

## 1. What this tool is, in one line

**Lakebridge reconcile tells you _what_ differs between a migrated source (Snowflake,
Oracle, Redshift, Teradata, …) and its Databricks target. ReconResolve tells you _why_ —
and whether each difference is a migration defect to fix or a genuine data difference —
with every verdict backed by an executed query.** It is the one-stop RCA layer that runs
**after** the Lakebridge reconcile step.

## 2. Where it sits (the big picture)

```
Source EDW ──(Lakebridge analyze → transpile)──▶ Databricks target
     │                                                   │
     └──────────────── Lakebridge reconcile ─────────────┘
                              │
                writes recon metadata tables
        (main · metrics · details · details_columns ·
         schema_details · recon_run_context · aggregate_*)
                              │
                              ▼
                      ★ ReconResolve RCA ★
        ingest → classify → confirm → enrich → (LLM) → report
                              │
                    reviewer-ready notebook + SUMMARY.md + JSON
```

You give it a `recon_id`; it produces a self-contained RCA notebook that a migration
engineer or data owner can act on.

## 3. The pipeline, stage by stage

1. **Ingest** (`rca_engine/ingest.py`) — reads the recon metadata for one `recon_id` and
   normalizes it into `Finding` objects (one per mismatched column / missing-rows / schema
   / threshold / aggregate / run-error). *Understands both the modern Lakebridge schema and
   the legacy one — see §5.*
2. **Classify** (`classify.py`) — deterministic first pass: probes + a per-dialect
   knowledge base assign each finding a **category**, a **verdict**, and a **confidence**.
3. **Confirm** (`drilldown.py`) — runs a live query per finding to confirm the hypothesis
   (nothing is promoted on a guess).
4. **Enrich** (all live, all best-effort):
   - **Distribution drift** (`drift.py`) — null-rate / cardinality / numeric shift.
   - **UC lineage trace-back** (`lineage.py`) — walks `system.access` lineage upstream to
     the layer where the difference entered (depth-agnostic).
   - **Job-level source trace** (`mismatch_trace.py`, `--trace-job`) — see §4.
   - **Aggregate RCA** (`aggregate_rca.py`) — for aggregates-reconcile runs.
   - **Suggested fixes + validation** (`fixgen.py`) — a runnable fix, marked ✅ only when a
     query proves it closes the gap.
   - **Blast radius** — downstream tables that consume the affected target.
5. **Tier-2 LLM fallback** (`resolve.py`) — only for the residual (needs-review/unknown);
   proposes a cause + confirming query, promoted only if the query confirms.
6. **Report** (`report.py`) — TL;DR, severity-ranked priorities, per-table notebooks,
   `SUMMARY.md`, JSON, and an append-only audit trail.

## 4. The headline features (what each does, when it fires, what you see)

| Feature | What it does | Flag / config |
|---|---|---|
| **Deterministic classification** | Categorizes each mismatch (type/precision, timezone, string-format, transpilation, volume, null/boolean, semi-structured, env-config, recon-config) with a verdict + confidence | always on |
| **Live confirmation** | Runs a query per finding to confirm before promoting | on (`--no-drilldown` to skip) |
| **UC lineage trace-back** | Walks column/table lineage upstream to the root layer where the diff entered | `--use-lineage` / `use_uc_lineage` |
| **Job-level source trace** | Finds the job that builds the target (from `system.access.table_lineage`), parses its notebook SQL with sqlglot, traces a mismatching column to its **true source columns** + emits a **reproduction query** that recomputes the bad row from source | `--trace-job` / `trace_job` |
| **Config-from-run_context** | Derives join keys / column mapping / transforms / thresholds / filters straight from `recon_run_context.config` — **no separate artifacts needed** | automatic fallback |
| **Aggregate-reconcile RCA** | Per-rule (MIN/MAX/SUM/COUNT/AVG…) aggregate mismatches from `aggregate_*` | on (`--no-aggregate` to skip) |
| **Threshold-aware verdicts** | `threshold_mismatch` (within a declared tolerance) → **benign / within-tolerance** | automatic |
| **Errored-run triage** | If the reconcile itself errored (`run_metrics.exception_message`), surfaces the error + config fix instead of "analyzing" meaningless metrics | automatic |
| **Schema RCA** | Type/precision/name divergence from the `schema_details` table | automatic |
| **Suggested + validated fixes** | Runnable remediation, ✅ only when a query proves it closes the gap | on |
| **Tier-2 LLM fallback** | Query-gated LLM cause proposal for the residual | `--endpoint` |
| **LLM-as-judge (eval)** | *Offline* grader of RCA output quality (verdict correctness, evidence sufficiency, fix validity, narrative faithfulness) — for benchmarking, never changes runtime RCA | `rca_engine/judge.py` / `rca-eval` skill |

## 5. How it leverages *all* of Lakebridge's output

| Lakebridge signal | What ReconResolve does with it |
|---|---|
| `metrics` (counts, mismatch_columns) | the core findings + totals |
| `details_columns` view / VARIANT `source_row`/`target_row` | per-column diff samples (modern); legacy `data<map>` auto-detected as fallback |
| `metrics.column_comparison.threshold_mismatch` | within-tolerance (benign) findings |
| `metrics.run_metrics.exception_message` | errored-run triage |
| `schema_details` | schema/type/precision RCA |
| `recon_run_context.config` | auto-derive the mapping (no artifacts) |
| `aggregate_rules/metrics/details` | aggregate-reconcile RCA |
| `main.source_type` | dialect → knowledge-base selection |

## 6. Verdicts (the field a human acts on)

- 🔧 **Migration-induced** — fix in the migration (code/type/pipeline/env). *Owner: migration engineer.*
- 📊 **Genuine data difference** — real source/upstream difference, not a migration bug. *Owner: data owner.*
- ✅ **Benign / within tolerance** — formatting-only or inside a declared threshold. *No action.*
- 🔍 **Needs review** — evidence inconclusive within budget (next check provided).

## 7. The two skills + the app

- **`rca-recon`** (Genie Code skill) — the primary agentic path: give it a `recon_id`, it
  generates the RCA notebook and runs every cell live. Config in `skill/rca-recon/config.yml`.
- **`rca-eval`** (new) — runs the RCA + the LLM judge over a `recon_id` or a fixture set and
  emits a quality/benchmark report. Used for benchmarking + regression scoring.
- **Databricks App** (`app/`) — a self-serve UI over the same engine.
- **CLI** — `python -m rca_engine.cli --recon-id … --recon-catalog … --recon-schema … [--trace-job] [--use-lineage] [--endpoint …]`.

## 8. The leadership demo (real, end-to-end)

A global retailer's **Sales & Revenue mart migrated from Amazon Redshift → Databricks**:
- **Source (Redshift):** star schema — `dim_customer` (1M), `dim_product` (100K),
  `dim_store` (2K), `dim_date`, **`fact_sales` (20M)**, `fact_inventory` (5M), plus gold
  rollups `daily_sales_by_store` (3.6M) and `product_revenue` (100K).
- **Lakebridge:** `analyze` (source assessment) → `transpile` (Redshift→Databricks SQL) →
  `reconcile` (source vs target).
- **Seeded defects in the target** (one per mechanism): precision loss on `net_revenue`,
  ~2K missing rows (a load filter), and a truncated `avg_realized_price` (transpilation).
- **ReconResolve** explains each with a query-backed verdict + fix.
- Source scripts: `migration/redshift_retail/source/`.

## 9. All-dialect coverage (beyond Redshift)

Standing up 7 live EDWs isn't practical, so the other dialects (Snowflake, Oracle,
Teradata, MSSQL, Synapse, BigQuery/Databricks) are modeled as a **source UC catalog → target
UC catalog**, with the ETL scripts sourced from a **Databricks job** (so the job-level source
trace + transpile fixtures apply), and the recon `source_type` set per dialect so the engine
auto-selects the right knowledge base. These fixtures double as the **benchmarking + stress**
bed.

## 10. How to run it (quick)

```bash
# discover recon runs
python -m rca_engine.cli --list --recon-catalog <cat> --recon-schema reconcile \
  --warehouse-id <WID> --profile <profile>

# analyze one, with the richest evidence
python -m rca_engine.cli --recon-id <RID> --recon-catalog <cat> --recon-schema reconcile \
  --dialect <redshift|snowflake|…> --warehouse-id <WID> --profile <profile> \
  --use-lineage --trace-job --output-dir rca_out
```

The engine falls back to `recon_run_context.config` for the mapping automatically, so you
don't need to pass transpiled-SQL artifacts unless you want to.

---

*Companion repo docs: `README.md` (overview + data-flow diagram), `docs/FEATURE_REFERENCE.md`
(function/flag-level reference), `docs/data_flow.md`, `docs/lakebridge_output_analysis.md`
(what Lakebridge writes + the gap analysis this build closed).*
