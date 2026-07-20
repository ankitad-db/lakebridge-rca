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

- `rca_engine/` - source-agnostic diagnostics package (probes, knowledge base, classifier, report).
- `rca-recon/` - the Genie Code skill (`SKILL.md`, `reference.md`, `config.yml`, `scripts/`).
- `migration/` - realistic retail-sales migration test bed (source_sim -> target, Jobs pipeline, seeded defects).
- `notebooks/` - RCA notebook template.
- `tests/` - unit tests for the engine.

## Status

Under active construction. See the build plan for phase-by-phase progress.
