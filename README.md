# RCA Genie-Code Skill for Migration Reconciliation

[![CI](https://github.com/ankitad-db/lakebridge-rca/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitad-db/lakebridge-rca/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Automates root-cause analysis (RCA) of data mismatches found by
[Lakebridge](https://github.com/databrickslabs/lakebridge) reconciliation during
data-warehouse migrations (Snowflake-first, source-agnostic core).

Lakebridge reconcile tells you **what** differs (row- and column-level). This project tells
you **why** — and whether the difference is a **migration defect** to fix or a **genuine data
difference** that is not a migration problem at all.

```
Lakebridge reconcile (detection)  ->  recon output tables (main / metrics / details)
        -> Genie Code `rca-recon` skill (root-cause analysis)
        -> RCA notebook: TL;DR + per-finding verdicts + evidence + fixes  (+ JSON)
```

You pass a `recon_id` in the Databricks Genie Code UI; the skill runs live, queries the real
source/target data in Unity Catalog, executes a confirmation query per finding, and iterates
until every finding has a verdict.

## Verdicts

Every finding gets a verdict, separate from its technical category:

- 🔧 **Migration-induced** — fix in the migration (code/transpilation, type/schema, pipeline, environment).
- 📊 **Genuine data difference** — real source/upstream difference; route to the data owner (not a migration bug).
- ✅ **Benign / expected** — formatting-only or within tolerance.
- 🔍 **Needs review** — evidence inconclusive within the query budget.

Each finding is cross-confirmed by up to **five independent sources**: recon data + target code
+ source types + UC lineage + a live query.

## Repository layout

```
rca_engine/            # source-agnostic diagnostics package (the engine)
  ingest.py            #   reads recon main/metrics/details -> findings + summaries
  probes/              #   numeric, temporal, string, null/boolean, semi-structured
  knowledge/           #   per-dialect knowledge base (snowflake.yaml)
  classify.py          #   signals + KB -> category + verdict + confidence
  lakebridge.py        #   parse recon config / transpiled SQL / source DDL (sqlglot)
  lineage.py           #   optional Unity Catalog lineage evidence
  drilldown.py         #   live confirmation queries -> finalize verdicts
  report.py            #   TL;DR + symbol-coded RCA notebook + JSON
  runners.py           #   QueryRunner: Spark (notebook) + Statement API (local)
  cli.py               #   `rca-run` entrypoint
skill/rca-recon/       # the Genie Code skill (SKILL.md, config.yml, vendored engine)
migration/             # realistic Snowflake->Databricks test bed (see migration/README.md)
  scenarios.yaml       #   machine-readable ground-truth oracle (22 scenarios)
  edge_cases/          #   edge-case source/target tables
tests/                 # 55 deterministic pytest cases (no workspace needed)
scripts/               # validate_scenarios.py — integration harness vs the oracle
docs/                  # one-pagers + pitch layout
```

## Prerequisites

- **Python** 3.10+ and [`uv`](https://docs.astral.sh/uv/) or `pip`.
- **Databricks CLI** authenticated to your workspace (`databricks auth login`), with a profile
  (this repo uses `ps-dr-east` by default) and a **SQL warehouse**.
- **Unity Catalog** access to the reconcile output and the source/target tables.
- **Lakebridge** (`databricks labs install lakebridge`) to run reconcile — only needed to
  produce a `recon_id`; the RCA itself just reads the recon output.

## Installation (development)

```bash
git clone https://github.com/ankitad-db/lakebridge-rca.git
cd lakebridge-rca

python -m venv .venv && source .venv/bin/activate      # or: uv venv && source .venv/bin/activate
pip install -e ".[dev,code,databricks]"                # engine + tests + sqlglot + connector
```

Verify the install:

```bash
make test        # or: pytest
make lint        # or: ruff check .
```

## Quickstart

### A. As a Genie Code skill (primary use)
Sync the skill (vendors the engine into the skill folder, then imports it to your workspace):

```bash
./sync_skill.sh ps-dr-east          # profile arg optional (default: ps-dr-east)
```

In Databricks **Genie Code (Agent mode)**, the `rca-recon` skill is auto-discovered. Give it a
`recon_id`; it generates the RCA notebook, asks for your approval, then runs all cells live.
Configuration (catalog/schema/dialect/output location/optional artifacts) lives in
`skill/rca-recon/config.yml`.

### B. Locally, against a reconcile run (CLI)

```bash
python -m rca_engine.cli \
  --recon-id <RECON_ID> \
  --recon-catalog <catalog> --recon-schema reconcile \
  --dialect snowflake \
  --warehouse-id <WAREHOUSE_ID> --profile ps-dr-east \
  --output-path rca_out
# optional code-aware inputs:
#   --recon-config <path> --transpiled-output <dir> --source-scripts <dir> \
#   --transpile-errors <file> --use-lineage
```

Produces `rca_out.json` and `rca_out.ipynb`.

### C. Run the tests (no workspace needed)

```bash
pytest                       # 55 deterministic unit tests
```

## End-to-end setup (test bed → recon → RCA)

To exercise the full pipeline on the bundled Snowflake→Databricks test bed:

1. **Deploy the test bed** — see [`migration/README.md`](migration/README.md). In short:
   ```bash
   cd migration
   python run_sql.py --file source_sim/02_create_source_sim.sql --warehouse-id <WID> --profile ps-dr-east
   python run_sql.py --file target/10_target_ddl.sql             --warehouse-id <WID> --profile ps-dr-east
   python run_sql.py --file pipeline/21_silver_transform.sql     --warehouse-id <WID> --profile ps-dr-east
   python run_sql.py --file pipeline/22_gold_aggregate.sql       --warehouse-id <WID> --profile ps-dr-east
   # comprehensive edge cases:
   python run_sql.py --file edge_cases/40_edge_source.sql        --warehouse-id <WID> --profile ps-dr-east
   python run_sql.py --file edge_cases/41_edge_target.sql        --warehouse-id <WID> --profile ps-dr-east
   ```
2. **Configure + run Lakebridge reconcile** (using `migration/recon/30_reconcile_config.json`)
   to produce a `recon_id`. Details in `migration/README.md`.
3. **Run the RCA** — invoke the skill in Genie Code with the `recon_id` (A), or the CLI (B).
4. **Validate against the oracle** (optional, CI-style):
   ```bash
   python scripts/validate_scenarios.py --recon-id <RECON_ID> --warehouse-id <WID>
   ```

## Configuration reference (`skill/rca-recon/config.yml`)

| Key | Purpose |
|---|---|
| `recon_catalog`, `recon_schema` | where Lakebridge writes recon output |
| `dialect` | source EDW dialect → selects the knowledge base |
| `output_dir` | where the RCA notebook lands (bare name → user home; absolute → UC Volume/Workspace) |
| `warehouse_id` | SQL warehouse (local/CLI runs) |
| `recon_config_path` | recon config JSON (join keys, column mapping, filters) — *the mapping* |
| `transpiled_output_dir` | transpiled/target Databricks SQL — per-column transforms |
| `source_scripts_dir` | original-dialect DDL — declared source types |
| `transpile_error_file` | Lakebridge transpile error report |
| `tables:` | explicit per-table source/target script manifest (overrides folder scans) |
| `use_uc_lineage` | attach Unity Catalog lineage evidence (default: false) |

## Testing & quality

- **Unit tests** (`tests/`, no workspace): `pytest` — probes, classifier, Lakebridge parsing, report.
- **Integration harness** (`scripts/validate_scenarios.py`): checks live `analyze()` output against
  the ground-truth oracle for every deployed scenario.
- **CI** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)): ruff + pytest on Python
  3.10/3.11/3.12, plus a check that the vendored skill engine matches `rca_engine/`.
- **Lint/format**: `ruff` (config in `pyproject.toml`).

## Documentation

- [`docs/one_pager_1_current_project.md`](docs/one_pager_1_current_project.md) — the "As-Is" blueprint.
- [`docs/one_pager_2_global_asset.md`](docs/one_pager_2_global_asset.md) — the "To-Be" global-asset package.
- [`docs/pitch_deck_layout.md`](docs/pitch_deck_layout.md) — pitch layout with personas.
- [`skill/rca-recon/SKILL.md`](skill/rca-recon/SKILL.md) — skill contract, examples, edge cases.
- [`skill/rca-recon/references/taxonomy.md`](skill/rca-recon/references/taxonomy.md) — category ↔ verdict mapping.
- [`migration/scenarios.md`](migration/scenarios.md) — human-readable scenario catalog.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, adding a probe or a dialect pack, keeping the
vendored engine in sync, and the PR checklist.

## License

MIT — see [LICENSE](LICENSE).
