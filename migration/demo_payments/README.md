# Demo payments bed — the "two tiers" scenario

A single Snowflake→Databricks **payments** migration, built to contrast the RCA's **two
tiers** in one realistic story: a mechanical defect the deterministic engine nails, and a
business-logic regression only the **LLM fallback** can name — each still backed by an
executed query.

## The pipeline

```
payments_src ──reconciled against──►  payments_gold (LEAF, join payment_id)

target pipeline (all CTAS → real UC lineage):

  payments_raw ....................... L2 root (correct values)
     │
     ▼
  payments_enriched .................. L1  ⚠ TWO DEFECTS
     │                                     • payment_ts : + 5:30, no UTC norm   → Tier 1
     │                                     • net_amount : round(gross*1.08,2)   → Tier 2
     ▼
  payments_gold ...................... L0 the reconciled leaf
```

## The story

The business truth (source): `net_amount = ROUND(gross_amount * 0.90, 2)` — a **10 % loyalty
discount**. During migration a developer rewrote the transform and applied an **8 % tax**
instead: `net_amount = ROUND(gross_amount * 1.08, 2)`. Same `DECIMAL` scale, no rounding
pattern, ratio ≈ 0.83 (not a clean 10×/100× factor) — so **no deterministic probe fingerprints
it**. `payment_ts` is separately shifted `+5:30` with no UTC normalization.

## What one bed proves

| Tier | Column | How it resolves |
|---|---|---|
| **Tier 1 · deterministic** | `payment_ts` | Temporal probe recognizes the constant `+5:30` offset → **timezone / migration_induced**. No LLM. |
| **Tier 2 · LLM fallback** | `net_amount` | No probe fires → **needs-review**. Claude reads the samples + the migrated derivation, hypothesizes the `×1.08` tax, and writes an **exact-reconstruction confirming query**; it passes → promoted to **transpilation / migration_induced**. |
| **The gate holds** | `net_amount` | A first, ratio-based hypothesis **failed** the query gate and stayed needs-review; only the exact reconstruction promoted it. *The query is the gate — never an LLM guess.* |
| **Clean controls** | `customer_id`, `gross_amount`, `currency`, `status` | Match everywhere → **no finding**. |

## Deploy

```bash
cd migration
python run_sql.py --file demo_payments/70_demo_payments_pipeline.sql \
  --warehouse-id 4c79c6902dd2bbc2 --profile ps-dr-east
```

## Run the whole thing end to end (deploy + recon + RCA + Claude fallback)

```bash
python scripts/run_payments_demo.py \
  --profile ps-dr-east --warehouse-id 4c79c6902dd2bbc2 \
  --endpoint databricks-claude-opus-5
```

The driver deploys the pipeline, reconciles `payments_src → payments_gold` (fresh
`recon_id`), runs the deterministic RCA, then asks a **Claude** Foundation Model endpoint to
resolve the residual `net_amount` — promoting it **only if** the confirming query passes.
Reuse an existing run with `--skip-deploy --recon-id <id>`.

## Expected result (the oracle)

Machine oracle: [`scenarios_demo_payments.yaml`](scenarios_demo_payments.yaml).

| id | column | tier | expected |
|----|--------|------|----------|
| PT1 | `payment_ts` | deterministic | `timezone` / 🔧 migration_induced |
| PN1 | `net_amount` | LLM fallback | `transpilation` / 🔧 migration_induced (confirmed by query) |
| — | `customer_id`, `gross_amount`, `currency`, `status` | — | clean (no finding) |

> **Verified live** on `fevm_ps_dr_us_east_2_catalog.mig_demo_payments` with
> `databricks-claude-opus-5` (the best-suited reasoning model for the fallback). Claude back-solved
> both formulas and confirmed with:
> `count_if(NOT (t.net_amount <=> ROUND(s.gross_amount*1.08,2)))=0 AND count_if(NOT (s.net_amount <=> ROUND(s.gross_amount*0.90,2)))=0 AS confirmed`.
