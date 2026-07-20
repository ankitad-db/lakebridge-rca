# RCA Genie-Code Skill for Migration Reconciliation

Automates root-cause analysis (RCA) of data mismatches found by
[Lakebridge](https://github.com/databrickslabs/lakebridge) reconciliation during
data-warehouse migrations (Snowflake-first, source-agnostic core).

Lakebridge reconcile tells you **what** differs (row- and column-level). This
project tells you **why** - and whether the difference is a **migration defect**
or a **genuine data difference** that is not a migration problem at all.

## How it fits together

```
Lakebridge reconcile (detection)  ->  recon output tables (main/metrics/details)
        -> Genie Code `rca-recon` skill (root-cause analysis)
        -> RCA notebook: TL;DR + per-finding verdicts + evidence + fixes
```

You pass a `recon_id` in the Databricks Genie Code UI; the skill runs live,
queries the real source/target data in Unity Catalog, and iterates until every
finding has a verdict.

## Verdicts

Every finding gets a verdict, separate from its technical category:

- **Migration-induced** - fix in the migration (code/transpilation, type/schema, pipeline, environment).
- **Genuine data difference** - real source/upstream difference; route to the data owner (not a migration bug).
- **Benign / expected** - formatting-only or within tolerance.
- **Needs review** - evidence inconclusive within the query budget.

## Layout

- `rca_engine/` - source-agnostic diagnostics package: `ingest` (reads recon
  `main`/`metrics`/`details`), `probes/` (numeric, temporal, string, null/boolean,
  semi-structured), `rowpattern`/`freshness`/`codecorr` analyzers, `knowledge/`
  (per-dialect KB), `classify` (verdict + category + confidence), `report`
  (TL;DR + notebook), `runners` (Spark + local statement API), and `cli`.
- `skill/rca-recon/` - the Genie Code skill (`SKILL.md`, `config.yml`,
  `scripts/run_rca.py`, `references/taxonomy.md`).
- `migration/` - realistic retail-sales migration test bed (source_sim -> target,
  medallion pipeline, reconcile config, and `scenarios.md` ground truth).

## Run it

In Genie Code (Agent mode), the `rca-recon` skill is auto-discovered; give it a
`recon_id` and it generates + runs the live RCA notebook.

Locally, against a reconcile run:

```bash
python -m rca_engine.cli --recon-id <RECON_ID> \
  --recon-catalog <catalog> --recon-schema reconcile \
  --dialect snowflake --warehouse-id <warehouse> --output-path rca_out
```

## Validation

Run end-to-end against a real Lakebridge reconcile (`databricks` source) over the
`migration/` test bed's 10 injected defects: the engine classifies **13/13
findings** with the correct verdict and category (see `migration/scenarios.md`).
