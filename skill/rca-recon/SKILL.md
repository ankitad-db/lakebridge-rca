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
- **From `config.yml` (this skill folder):** `recon_catalog`, `recon_schema`,
  `dialect` (the original source EDW dialect, e.g. `snowflake`), and an optional
  `warehouse_id`. Read it with a small YAML load; do not ask the user for these.

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

cfg = yaml.safe_load(open("config.yml"))            # relative to this skill folder
recon_id = "<RECON_ID_FROM_USER>"

result = analyze(
    SparkQueryRunner(spark), recon_id,
    cfg["recon_catalog"], cfg["recon_schema"],
    dialect=cfg.get("dialect", "snowflake"), drilldown=True,
)
print(build_tldr(result))
write_notebook(result, f"/tmp/rca_{recon_id}.ipynb")   # readable, symbol-coded report
```

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
- `write_notebook(result, "/tmp/rca_<recon_id>.ipynb")` emits a symbol-coded report
  grouped by verdict: a TL;DR table (counts by verdict) followed by one section per
  finding with category/confidence/owner, root cause, fix, the confirming query +
  its evidence, and sample diffs. Re-run any query cell to drill deeper.
- End with the **TL;DR** from `build_tldr(result)`: counts by verdict, headline root
  causes, and a clear "what to fix vs. what to route to the data owner" list.

### 5. Confirm with the user, then run all cells
- After writing the notebook, **pause and ask the user for approval** before
  executing it. Show the TL;DR and the notebook path, then ask explicitly, e.g.:
  _"The RCA notebook is generated at `/tmp/rca_<recon_id>.ipynb`. Are the findings
  and proposed fixes acceptable? Reply **yes** to run all cells, or tell me what to
  adjust."_
- **Do not run the notebook until the user confirms.** If they request changes
  (reclassify a finding, add a drill-down, tweak a fix/owner), apply them, regenerate
  the notebook, and ask again.
- **On approval, run all cells** top-to-bottom so every confirming query executes
  live and the outputs are captured in the notebook. Then report that the run
  completed and restate the final verdict counts.

## Rules

- Never label something migration-induced without checking it could be a genuine
  data difference (especially NULL-in-source, stale-snapshot, and partial-column
  mismatches). When source is NULL/absent and target is populated, it is genuine
  data unless proven otherwise.
- Prefer deterministic evidence (a query result) over narrative. Every verdict
  must cite the query that supports it.
- If a mismatch cannot be explained after drill-down, mark it **needs review** and
  say exactly which query/owner would resolve it. Do not guess.
