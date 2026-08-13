# Demo diamond bed — the flagship end-to-end scenario

A single Snowflake→Databricks "orders" migration, shaped as a **diamond**, built to show the
**maximum** of what the RCA does in one coherent story — via **both** the Genie Code skill
and the Databricks App.

## The pipeline

```
orders_src ──reconciled against──►  orders_gold_c (LEAF E)   and   orders_gold_d (LEAF F)

target pipeline (all CTAS → real UC lineage):

  orders_raw ......................... L3 root (correct values)
     │
     ▼
  orders_enriched .................... L2  ⚠ SHARED DEFECTS (fan out to BOTH arms)
     │      │                                • amount : cast → DECIMAL(18,2)  (scale loss)
     │      │                                • order_ts: + 5:30, no UTC norm  (timezone)
     ├──────┘
     ▼            ▼
  curated_c     curated_d ............. L1
  ⚠ sku         ⚠ volume                    arm C: sku → lower()+trailing space
  distractor    watermark                   arm D: drops order_id > 470
     │             │
     ▼             ▼
  gold_c        gold_d ................ L0  the two reconciled leaves (E / F)
```

## What one bed proves

| Feature | How this bed shows it |
|---|---|
| **Depth-agnostic trace-back** | `amount`/`order_ts` surface on the leaf but the defect is **2 hops up** at `orders_enriched`; `sku` is **1 hop up** at `orders_curated_c`. The walk reaches root `orders_raw`. |
| **Root-cause clustering** | `amount` + `order_ts` appear on **both** leaves → collapse to **one shared root** (`orders_enriched`). "Fix one, resolve many." |
| **Downstream blast-radius** | From `orders_enriched`, UC lineage lists `curated_c, curated_d, gold_c, gold_d` as impacted. |
| **Distractor isolation** | `sku` only appears in the **arm-C** (`gold_c`) trace — never `gold_d`. The walk only follows the leaf's own ancestry. |
| **Four categories** | `type_precision` (amount), `timezone` (order_ts), `string_format` (sku), `volume_missing` (arm D rows). |
| **Clean controls** | `customer_id`, `status`, `region` match everywhere → **no finding** (proves precision). |
| **Code-aware (sqlglot)** | The [manifest](table_manifest.yml) feeds source + target scripts so each finding cites the exact transform (`cast(amount AS DECIMAL(18,2))`, `+ 5:30`, `concat(lower(sku),' ')`). |
| **Suggested fixes + gate** | Each finding gets a runnable fix; the validation gate dry-runs it on sampled keys. |
| **Memory / audit / notebook** | Second run auto-proposes known causes; every step lands in the audit table; a reviewer-ready RCA notebook is published. |

## Deploy

```bash
cd migration
python run_sql.py --file demo_diamond/60_demo_diamond_pipeline.sql \
  --warehouse-id 4c79c6902dd2bbc2 --profile ps-dr-east
```

> **Lineage latency:** UC lineage (`system.access.column_lineage` / `table_lineage`) is
> populated asynchronously — allow a few minutes after the CTAS runs before the trace-back
> has data. Requires `SELECT` on `system.access.*_lineage`.

## Reconcile

Use [`../recon/35_reconcile_config_demo_diamond.json`](../recon/35_reconcile_config_demo_diamond.json)
(source `orders_src` → targets `orders_gold_c` and `orders_gold_d`, join `order_id`, schema
`fevm_ps_dr_us_east_2_catalog.mig_demo_diamond`). Reconcile via Lakebridge, the app-native
engine, or the App's **Trigger recon** page — any produces a `recon_id`.

## Run the RCA (both leaves, trace-back on)

Local CLI (per leaf `recon_id`):

```bash
python -m rca_engine.cli --recon-id <recon_id> \
  --recon-catalog fevm_ps_dr_us_east_2_catalog --recon-schema reconcile \
  --warehouse-id 4c79c6902dd2bbc2 --profile ps-dr-east \
  --table-manifest migration/demo_diamond/table_manifest.yml \
  --use-lineage --max-lineage-hops 10
```

The [demo runbook](../../docs/demo_diamond_runbook.md) walks the full end-to-end demo for both
the Genie Code skill and the App.

## Expected result (the oracle)

Machine oracle: [`scenarios_demo_diamond.yaml`](scenarios_demo_diamond.yaml).

| id | target | expected | trace-back |
|----|--------|----------|------------|
| DC1 / DD1 | `*.amount` | `type_precision` / 🔧 migration_induced | 3 hops → `orders_raw`, defect at `orders_enriched` |
| DC2 / DD2 | `*.order_ts` | `timezone` / 🔧 migration_induced | 3 hops → `orders_raw`, defect at `orders_enriched` |
| DC3 | `orders_gold_c.sku` | `string_format` / 🔧 migration_induced | defect at `orders_curated_c` (arm C only) |
| DD3 | `orders_gold_d` rows | `volume_missing` / 🔧 migration_induced | watermark in `orders_curated_d` |
| — | `customer_id`, `status`, `region`, `gold_d.sku` | clean (no finding) | n/a |

Validate against the oracle (checks category/verdict **and** the trace-back root/depth):

```bash
python scripts/validate_scenarios.py --recon-id <recon_id> \
  --warehouse-id 4c79c6902dd2bbc2 --recon-schema reconcile \
  --scenarios migration/demo_diamond/scenarios_demo_diamond.yaml --use-lineage
```
