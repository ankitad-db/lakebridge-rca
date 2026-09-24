# Deep-diamond demo bed — the whole feature set in one run

The **flagship** RCA test bed. A single Snowflake→Databricks migration, shaped as a 4-layer
diamond, that exercises **every** capability of the RCA engine in one reconcile run.

## Topology

```
raw_a  (clean root)                                              L3
   |
shared_b   ⚠ amount   cast DECIMAL(18,4)->(18,2)   [type_precision -> TIER 1 deterministic]
   |       ⚠ net_amount round(gross*1.08,2)         [business drift  -> TIER 2 LLM fallback]
  / \       (both defects share ONE upstream root)                L2
 /   \
branch_c  branch_d   ⚠ sku concat(lower(sku),'  ')  [string_format DISTRACTOR — arm D only]  L1
  |         |
leaf_e    leaf_f     (E<-C has NO sku; F<-D has sku)              L0  ← reconciled LEAVES
  |         |
report_e  report_f   (downstream consumers -> real BLAST RADIUS)
```

**Reconcile pairs (join `a_id`):** `leaf_e_src → leaf_e_tgt` and `leaf_f_src → leaf_f_tgt`.

## What it proves

| Capability | How this bed exercises it |
|---|---|
| **Tier 1 · deterministic** | `amount` (18,4→18,2 scale loss) and `sku` (lower()+trailing space) are probe-fingerprinted and drill-down-confirmed — no LLM. |
| **Tier 2 · LLM fallback** | `net_amount` = `round(gross×1.08,2)` (8% tax) vs source `×0.90` (10% discount). No probe fingerprints it → Claude proposes a hypothesis + a **confirming query**; promoted only when it passes. |
| **Deep lineage trace-back** | Every finding walks **3 hops** from the leaf back to root `raw_a`; the defect entered at `shared_b` (values) / `branch_d` (sku). |
| **Sibling isolation** | `leaf_e` (arm C) has no `sku` — column-scoped lineage keeps arm D's distractor **out** of arm C. |
| **Blast radius** | `leaf_e → report_e`, `leaf_f → report_f` give each fix a real downstream consumer to re-validate. |
| **Clustering** | `amount` collapses across both leaves to one `shared_b` root cause — fix once, resolve two. |
| **Clean controls** | `gross_amount`, `qty` match everywhere — no false positives. |

## Files

| File | Purpose |
|---|---|
| `72_demo_diamond_deep_pipeline.sql` | Deploys the whole bed (source leaves + target diamond + report consumers). |
| `source_snowflake/leaf_e_src.sql`, `leaf_f_src.sql` | Snowflake-dialect source DDL + declared business rules (code-aware inputs). |
| `target_databricks/leaf_e_gold.sql`, `leaf_f_gold.sql` | Migrated target transforms, inlined so sqlglot / the LLM can cite the exact expression. |
| `table_manifest.yml` | Maps each reconciled leaf to its source/target scripts + join keys. |
| `scenarios_demo_diamond_deep.yaml` | Ground-truth oracle (5 findings + isolation + clean controls). |

## Run it end to end

```bash
python scripts/run_diamond_deep_demo.py \
  --profile ps-dr-east --warehouse-id 4c79c6902dd2bbc2 \
  --endpoint databricks-claude-opus-5
```

The driver deploys the bed, reconciles both leaves under one `recon_id`, runs the deterministic
RCA (probes + drill-down + UC lineage trace-back + blast radius + clustering + code-aware mapping),
then the Tier-2 Claude fallback for the `net_amount` residuals, and prints a per-finding tier
summary plus the lineage / blast-radius / cluster evidence and the sibling-isolation check.

## Expected result (verified live)

`recon_id 1d04640331554f61874b47299b08f5b1` (500 rows/leaf):

```
leaf_e_tgt.amount      type_precision / migration_induced   [TIER 1 deterministic]
leaf_e_tgt.net_amount  transpilation  / migration_induced   [TIER 2 LLM confirmed]
leaf_f_tgt.amount      type_precision / migration_induced   [TIER 1 deterministic]
leaf_f_tgt.net_amount  transpilation  / migration_induced   [TIER 2 LLM confirmed]
leaf_f_tgt.sku         string_format  / migration_induced   [TIER 1 deterministic]

lineage: every finding traces 3 hops to root raw_a_tgt (defect at shared_b / branch_d)
blast:   leaf_e → report_e · leaf_f → report_f
cluster: "SQL translation via cast" — leaf_e.amount + leaf_f.amount → one root
isolation: leaf_e findings = [amount, net_amount] → PASS (no sku leakage)
```
