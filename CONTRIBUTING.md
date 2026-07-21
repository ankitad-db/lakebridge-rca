# Contributing

Thanks for improving the RCA Genie-Code accelerator. This guide covers local setup, the common
extension points, and the checks your change must pass.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,code,databricks]"
make test   # 55 unit tests, no workspace needed
make lint
```

## Project principles

- **Deterministic core.** The engine (`rca_engine/`) must run without a workspace; anything that
  needs live data goes through a `QueryRunner` so it can be unit-tested with fakes.
- **Evidence-first.** Every verdict cites the signal/query that supports it. Prefer adding a probe
  or a drill-down over hard-coding a conclusion.
- **Never break the pipeline.** Probes, code-correlation, lineage, and drill-down are defensive —
  a failure degrades gracefully and leaves the deterministic verdict in place.
- **Ground truth in `scenarios.yaml`.** New behavior should be backed by a scenario and a test.

## Common extension points

### Add a probe (new value-difference mechanism)
1. Add `rca_engine/probes/<name>.py` exposing `probe(source_value, target_value) -> list[ProbeSignal]`.
2. Register it in `rca_engine/probes/__init__.py` (`ALL_PROBES`).
3. Map its category → verdict in `rca_engine/classify.py` if it's a new category.
4. Add a scenario to `migration/scenarios.yaml` and a case to `tests/test_probes.py` /
   `tests/test_scenarios_unit.py`.

### Add a source dialect (dialect pack)
1. Add `rca_engine/knowledge/<dialect>.yaml` (type mappings, function differences, remediation).
2. Optionally add dialect-specific scenarios to the test bed.
3. Run with `--dialect <dialect>` (CLI) or `dialect:` in `config.yml`.

### Change the report / notebook
Edit `rca_engine/report.py`. Keep the section order aligned with Lakebridge (summary → overview →
match rates → validation → findings → conclusion) and update `tests/test_report.py`.

## Keep the vendored engine in sync

The skill ships a **vendored copy** of the engine at `skill/rca-recon/rca_engine/`. After changing
`rca_engine/`, re-vendor it (CI enforces they match):

```bash
make sync            # rsync rca_engine/ -> skill/rca-recon/rca_engine/ (no workspace import)
# or, to also import to the workspace:
./sync_skill.sh <profile>
```

## Checks your PR must pass

- [ ] `make lint` (ruff) is clean.
- [ ] `make test` (pytest) is green.
- [ ] Vendored engine matches source (`make check-sync`).
- [ ] New/changed behavior has a scenario in `scenarios.yaml` and a test.
- [ ] Docs updated if the input/output contract changed (README, SKILL.md).

## Commit / PR style

- Small, focused commits with imperative subject lines.
- Describe the *why* in the body; link the scenario/edge case where relevant.
