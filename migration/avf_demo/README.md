# AVF demo — validation-tool-agnostic RCA on AVF output

Proves the RCA runs on **AVF** (Auto Validation Framework) output, not just Lakebridge
reconcile. Real project scenario this models:

- **Validation tool:** AVF (not Lakebridge)
- **Source dialect:** Teradata — auto-detected from `avf_validation_summary.source_dialect`
- **Source access:** ADLS extracts (pre- and post-load) surfaced as Databricks tables — AVF
  validates the post-load target against the source extract; **no live source connection** is
  needed for RCA (we read AVF's output tables)
- **Scripts:** source + migrated SQL in GitHub — pass them for code-aware RCA via the engine's
  Git support (`source_scripts_git` / `transpiled_output_git`) or local `--code-dir`/`--source-dir`

The RCA engine is agnostic: `analyze(..., source=AVFSource(run_id, reports_schema))`. Nothing
downstream (classify / drill-down / fixes / notebook) knows which tool produced the output.
The Lakebridge path is unchanged (`analyze()` defaults to `LakebridgeSource`).

---

## Track 2 — runnable now (no AVF wheel required)

Seeds a *completed* AVF run's report tables covering **every** AVF feature, then runs our RCA:

```bash
python migration/avf_demo/seed_avf_reports.py          # prints RUN_ID=<uuid>, REPORTS_SCHEMA=...
python migration/avf_demo/run_rca_avf.py <RUN_ID>      # deterministic
python migration/avf_demo/run_rca_avf.py <RUN_ID> --endpoint databricks-claude-opus-5   # hybrid
```

Features exercised (one defect each), so the bundle shows the full RCA surface:

| AVF feature / table | Seeded defect | Our RCA |
|---|---|---|
| `avf_validation_columns_mismatch` (PK_BASED) | `amount` DECIMAL precision; `order_ts_utc` +5h timezone; `customer_name` case | per-column value RCA + verdict |
| `avf_validation_rows_mismatch` | 5 missing in target, 2 extra | volume_missing / volume_extra |
| `avf_validation_schema_mismatch` | `NUMBER(18,4)` → `DECIMAL(18,2)` | type/precision finding |
| `avf_validation_rca` | `FILTER_LOSS` on upstream `stg_sales` | attached as **evidence** on the volume finding |
| `avf_validation_bi_results` (METRICS/BI) | `revenue` aggregate variance | AGGREGATE finding |
| `source_dialect = teradata` | — | Teradata KB auto-selected |
| `primary_keys_used = order_id` | — | reused as join keys (no PK re-detection) |

The bundle lands in `app/bundles/rca_<run_id>/` and shows in the app like any other run.

---

## Track 1 — real AVF run (once the AVF wheel is deployed)

Use AVF's own onboarding to produce the real `avf_*` tables, then run **only** `run_rca_avf.py`:

1. Deploy AVF to the workspace (from the `databricks-auto-validator` repo):
   ```bash
   cd avf_onboarding && ./deploy.sh --profile ps-dr-east --catalog fevm_ps_dr_us_east_2_catalog
   ```
2. Point AVF at the source extract (pre-load) and migrated target (post-load), run the
   `UnifiedValidationOrchestrator` with `save_validation_reports=True` and
   `validation_reports_schema=<catalog>.<reports_schema>` → note the `run_id`.
3. RCA it:
   ```bash
   python migration/avf_demo/run_rca_avf.py <run_id> \
       --reports-schema <catalog>.<reports_schema> \
       --endpoint databricks-claude-opus-5
   ```

Nothing in step 3 changes between Track 1 and Track 2 — same engine, same `AVFSource`.

---

## Configuring the tool everywhere (not just this script)

- **Skill (Genie Code):** `skill/rca-recon/config.yml` → `validation_tool: avf`, `avf.reports_schema`,
  `rca_mode: hybrid|deterministic|agent`. The user still supplies just the run id.
- **App:** env `RCA_VALIDATION_TOOL=avf`, `RCA_AVF_REPORTS_SCHEMA=<catalog>.<schema>`.
- **Engine/CLI:** `analyze(..., source=AVFSource(run_id, reports_schema))`.
