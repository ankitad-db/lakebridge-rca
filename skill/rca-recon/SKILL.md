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
is explicitly flagged **needs review**.

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
The deterministic engine is the `rca_engine` package in the `lakebridge-rca`
repo. Ensure it is importable, then run the first pass:

```python
try:
    import rca_engine
except ImportError:
    %pip install git+https://github.com/ankitad-db/lakebridge-rca.git
    dbutils.library.restartPython()
```

### 2. Deterministic first pass (fast, no LLM guessing)
Use the in-notebook Spark session as the query backend:

```python
import yaml, json
from rca_engine.runners import SparkQueryRunner
from rca_engine.ingest import ingest
from rca_engine.classify import classify_all
from rca_engine.models import RcaResult
from rca_engine.report import build_tldr, build_notebook, write_notebook

cfg = yaml.safe_load(open("config.yml"))            # relative to this skill folder
recon_id = "<RECON_ID_FROM_USER>"

runner = SparkQueryRunner(spark)
findings = ingest(runner, recon_id, cfg["recon_catalog"], cfg["recon_schema"])
findings = classify_all(findings, dialect=cfg.get("dialect", "snowflake"))
result = RcaResult(recon_id=recon_id, dialect=cfg.get("dialect", "snowflake"), findings=findings)
print(build_tldr(result))
```

This reads `main` / `metrics` / `details`, runs deterministic probes, and gives
each finding a category, verdict, and confidence. See `references/taxonomy.md`
for how probes map to categories.

### 3. Live drill-down loop (this is the point of running live)
For every finding, **confirm the hypothesis with a real query** before trusting
it — and always drill down when confidence < 0.8 or verdict is `needs_review`.
Use these patterns (source = `main.source_table`, target = `main.target_table`):

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
resolved. Do **not** stop at the deterministic pass if anything is unresolved.

### 4. Produce the RCA notebook + conclusion
- Generate the notebook scaffold (`write_notebook(result, "/tmp/rca_<recon_id>.ipynb")`),
  then enrich each finding section with the live query, its output, the confirmed
  verdict, remediation (from the knowledge base), and the owner.
- End with a **TL;DR**: counts by verdict, the headline root causes, and a clear
  "what to fix vs. what to route to the data owner" list.

## Rules

- Never label something migration-induced without checking it could be a genuine
  data difference (especially NULL-in-source, stale-snapshot, and partial-column
  mismatches). When source is NULL/absent and target is populated, it is genuine
  data unless proven otherwise.
- Prefer deterministic evidence (a query result) over narrative. Every verdict
  must cite the query that supports it.
- If a mismatch cannot be explained after drill-down, mark it **needs review** and
  say exactly which query/owner would resolve it. Do not guess.
