# Using ReconResolve on your own reconciliation

A setup + step-by-step runbook for someone who has **already run a reconciliation**
(e.g. Lakebridge `reconcile`) on their **own data in their own Databricks workspace**, and
now wants ReconResolve to explain *why* the mismatches happened and whether each is a
**migration defect** or a **genuine data difference**.

You do **not** need to re-run the reconciliation. ReconResolve reads your existing recon
output plus the live source/target tables.

---

## 1. What you need (prerequisites)

- A **Databricks workspace** where:
  - your reconciliation already wrote its output tables — **`main`**, **`metrics`**,
    **`details`** — into some catalog + schema (this is your *recon output*), and
  - the **source and target tables** that were reconciled are query-able in Unity Catalog.
- A **SQL warehouse** (or an all-purpose/serverless cluster) you can run queries on.
- Unity Catalog **read access** (`SELECT`) to the recon output schema *and* the
  source/target tables.
- The **`recon_id`** of the run you want to analyze (how to find it is in Step 3).
- One of:
  - **Genie Code** in that workspace (recommended, agentic path), **or**
  - **Python 3.10+** and the **Databricks CLI** on your laptop (local/CLI path).

> RCA is **source-agnostic**. Knowledge bases ship for `snowflake`, `oracle`, `teradata`,
> `mssql` (SQL Server), and `synapse`. Any other source still runs with the generic probes;
> it just gets no dialect-specific remediation text.

---

## 2. What RCA reads (inputs)

| Input | Required? | What it is |
|---|:--:|---|
| Recon output: `main` / `metrics` / `details` | ✅ | The reconciliation result tables (what differs, row- and column-level). |
| Source & target tables (in UC) | ✅ | Read live to confirm each hypothesis with a real query. |
| `recon_id` | ✅ | Identifies which run to analyze. |
| Recon **config JSON** (join keys, column mapping, filters) | optional | Exact join keys / renamed-column mapping (else auto-detected). |
| **Transpiled target SQL** + **source DDL/scripts** | optional | Enables *code-aware* RCA (confirms cause from the migrated code, not just data). |
| Transpile error report | optional | Surfaces known translation warnings. |

Everything optional degrades gracefully — omit it and RCA runs purely data-driven.

---

## 3. Find your `recon_id`

If you don't already have it, list recent runs from your recon output schema:

```bash
python -m rca_engine.cli --list \
  --recon-catalog <YOUR_CATALOG> --recon-schema <YOUR_RECON_SCHEMA> \
  --warehouse-id <YOUR_WAREHOUSE_ID> --profile <YOUR_CLI_PROFILE>
```

This prints a table of recent `recon_id`s with start time, table-pair count, and how many
had diffs. Pick one.

---

## 4. Point ReconResolve at *your* workspace

This is the only real "setup" — tell it where your data lives. Edit
`skill/rca-recon/config.yml` (for the Genie Code path) or pass the equivalent CLI flags
(for the local path):

| Config key | CLI flag | Set it to |
|---|---|---|
| `recon_catalog` | `--recon-catalog` | the catalog holding your `main`/`metrics`/`details` |
| `recon_schema` | `--recon-schema` | the schema holding them (often `reconcile`) |
| `dialect` | `--dialect` | your **source** system: `snowflake` \| `oracle` \| `teradata` \| `mssql` \| `synapse` |
| `warehouse_id` | `--warehouse-id` | your SQL warehouse id (local/CLI runs) |
| `output_dir` | `--output-dir` | where to write the RCA notebook bundle (workspace folder, UC Volume, or local dir) |

Leave everything else at defaults for a first run.

---

## 5A. Run it — Genie Code skill (recommended)

1. **Deploy the skill to your workspace** (from a clone of this repo, authenticated to
   *your* workspace):
   ```bash
   ./sync_skill.sh <YOUR_CLI_PROFILE>
   ```
   This vendors the engine into the skill and imports it to
   `/Users/<you>/.assistant/skills/rca-recon` in your workspace.
2. Open **Genie Code (Agent mode)** — the `rca-recon` skill is auto-discovered.
3. Prompt it with your `recon_id`:
   ```
   Use the rca-recon skill to run root-cause analysis on recon_id <YOUR_RECON_ID>.
   Generate the RCA notebook bundle, ask for my approval, then run all cells live.
   Give me the TL;DR: verdict counts, systemic root-cause clusters, and the suggested
   fixes (flag which are ✅ validated).
   ```
4. Review the generated notebook + `SUMMARY.md` it publishes to your `output_dir`.

## 5B. Run it — local CLI (no Genie needed)

```bash
git clone <this-repo-url> && cd <repo>
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,code,databricks]"

python -m rca_engine.cli \
  --recon-id <YOUR_RECON_ID> \
  --recon-catalog <YOUR_CATALOG> --recon-schema <YOUR_RECON_SCHEMA> \
  --dialect <YOUR_SOURCE_DIALECT> \
  --warehouse-id <YOUR_WAREHOUSE_ID> --profile <YOUR_CLI_PROFILE> \
  --output-dir rca_out
# optional code-aware inputs:
#   --recon-config <path> --transpiled-output <dir> --source-scripts <dir> \
#   --transpile-errors <file> --use-lineage --combined-notebook
```

---

## 6. Large tables? Keep the scans cheap (important)

RCA reads the pre-computed recon output and a **sample** of differing rows cheaply, but its
*confirming*, *drift*, and *fix-validation* queries aggregate over the source/target. On big
tables, bound them (this is **on by default**, and stays exact):

- **`scan_mode: scoped`** (default) — column confirms re-check only the reconciliation
  **flagged keys** (`IN (...)` push-down), not the whole table. The true total mismatch
  count still comes from the recon metrics.
- **Partition/date window** — set these so full-table aggregates read one partition instead
  of full history (the column must exist on **both** source and target):
  ```yaml
  scan_partition_column: "load_dt"
  scan_date_start: "2024-01-01"
  scan_date_end: "2024-01-31"
  ```
- `scan_mode: full` restores unbounded scans (fine for small tables / a test bed).

---

## 7. Permissions checklist

Grant these to **whoever runs RCA** (your user for CLI; the skill's principal for Genie):

| Action | Needs |
|---|---|
| Read recon output | `SELECT` on `<recon_catalog>.<recon_schema>` |
| Confirm hypotheses live | `SELECT` on the source & target tables/schemas |
| Run queries | access to the SQL warehouse |
| (Optional) UC lineage / blast radius | `SELECT` on `system.access.*_lineage` |
| (Optional) audit trail | `CREATE TABLE` + `MODIFY` on the audit schema (auto-created on first write) |

---

## 8. What you get (outputs)

A self-contained **`rca_<recon_id>/`** folder:

- **`00_index.ipynb`** — overview + severity-ranked **top priorities** + per-table routing.
- **one notebook per reconciled table** — every finding with: **verdict** (🔧 migration /
  📊 genuine data / ✅ benign / 🔍 needs review), root cause, the evidence + the **executed
  confirming query**, sample diffs, distribution drift, and a **runnable suggested fix**
  (marked **✅ validated** when a query proves it closes the gap).
- **`SUMMARY.md`** — paste into a ticket / Slack / email.
- **`rca_<recon_id>.json`** — machine-readable findings.

Every verdict cites an executed query — it's evidence, not a guess.

---

## 9. Troubleshooting

- **"Table or view not found" on the recon output** → check `recon_catalog` /
  `recon_schema` point at the schema that actually holds `main`/`metrics`/`details`.
- **Confirming queries fail / permission denied** → you're missing `SELECT` on the source
  or target tables (RCA reads them live).
- **Join keys look wrong / findings under-explained** → pass the recon **config JSON**
  (`recon_config_path` / `--recon-config`) so exact join keys and renamed-column mappings
  are used instead of the auto-detected guess.
- **Queries too slow / expensive** → set the partition window in §6 (or narrow the run to a
  recent load).
- **No dialect-specific remediation** → set `dialect` to your actual source system.

---

## 10. FAQ

- **Do I need to re-run reconciliation?** No — RCA consumes your existing recon output.
- **Does it change my data?** No. RCA only **reads**; suggested fixes are shown as
  review-then-run cells and are never auto-applied.
- **Does it need internet / external packages in the workspace?** No — the engine is
  vendored inside the skill, so Genie Code imports it directly.
- **Can I analyze one table at a time?** Yes — the skill and CLI both support scoping to a
  single table pair.
