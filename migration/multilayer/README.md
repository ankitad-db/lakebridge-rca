# Multi-layer lineage test bed

A purpose-built bed for the **depth-agnostic upstream trace-back**. It proves the RCA can
walk lineage past the reconciled target, through intermediate layers, to the layer where a
difference actually entered — regardless of how many layers there are.

## The pipeline

A medallion pipeline where the defect is injected in an **intermediate** layer and passed
through unchanged to the reconciled target. The target's *immediate* parent is clean, so the
engine must walk **past the first hop** to find the cause.

```
sales_src  ─(reconciled against)─►  sales_gold        ← the recon compares these two
                                        │  (L4 target, clean passthrough)
                                        ▼
                                     sales_curated     ← L3, clean passthrough
                                        │
                                        ▼
                                     sales_stg  ⚠BUG   ← L2, round(amount,0) — defect enters here
                                        │
                                        ▼
                                     sales_raw         ← L1 root, correct values
```

- `amount` (`DECIMAL(18,4)`) is **rounded to whole units** in `sales_stg` and flows unchanged
  to `sales_gold`. Reconciling `sales_src` (correct) vs `sales_gold` flags `amount`; the
  root cause is **2 hops upstream** at `sales_stg`.
- `qty` (`INT`) is an **untouched passthrough** through every layer → must produce **no
  finding** (the trace-back only fires on the genuinely mismatched column).

Every table is created with `CTAS`, so Unity Catalog records column/table lineage
(`gold ← curated ← stg ← raw`) that the trace-back walks.

## Deploy

```bash
python run_sql.py --file multilayer/50_multilayer_pipeline.sql \
  --warehouse-id <WID> --profile <profile>
```

> **Lineage latency:** UC lineage (`system.access.column_lineage` / `table_lineage`) is
> populated asynchronously from query history — allow a few minutes after the CTAS runs
> before the trace-back has data. Requires `SELECT` on `system.access.*_lineage`.

## Reconcile

Use [`../recon/34_reconcile_config_multilayer.json`](../recon/34_reconcile_config_multilayer.json)
(source `sales_src` → target `sales_gold`, join `sale_id`; both in
`fevm_ps_dr_us_east_2_catalog.mig_multilayer`) to produce a `recon_id`. Import it like the
other configs (see [`../recon/README.md`](../recon/README.md)) and run
`databricks labs lakebridge reconcile`.

## Run the RCA with trace-back on

Genie Code skill — set in `skill/rca-recon/config.yml`:

```yaml
recon_schema: reconcile
use_uc_lineage: true      # turns on lineage + the depth-agnostic trace-back
max_lineage_hops: 10
```

then prompt: *"Run RCA on recon_id `<multilayer_recon_id>`. For `sales_gold.amount`, show the
upstream lineage trace-back and tell me which layer the difference entered at."*

Local CLI:

```bash
python -m rca_engine.cli --recon-id <multilayer_recon_id> \
  --recon-catalog fevm_ps_dr_us_east_2_catalog --recon-schema reconcile \
  --warehouse-id <WID> --profile <profile> --use-lineage --max-lineage-hops 10
```

## Expected result (the oracle)

Machine oracle: [`scenarios_multilayer.yaml`](scenarios_multilayer.yaml).

| id | target | expected category / verdict | trace-back |
|----|--------|------------------------------|------------|
| ML1 | `sales_gold.amount` | `transpilation` / 🔧 migration_induced | `Lineage trace-back (3 hops to root sales_raw): sales_gold.amount ← sales_curated.amount ← sales_stg.amount ← sales_raw.amount` — points at **`sales_stg`** |
| — | `sales_gold.qty` | clean (no finding) | n/a |

Validate against the oracle (checks category/verdict **and** that the trace-back reached
`sales_raw` at depth 3):

```bash
python scripts/validate_scenarios.py --recon-id <multilayer_recon_id> \
  --warehouse-id <WID> --recon-schema reconcile \
  --scenarios migration/multilayer/scenarios_multilayer.yaml --use-lineage
```

This bed backs **section L** of [`docs/genie_skill_test_plan.md`](../../docs/genie_skill_test_plan.md).
