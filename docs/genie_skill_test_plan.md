# ReconResolve — Genie Code skill test plan

There are two layers of tests:
- **A. Functional / behavioral** — work in any workspace, against any `recon_id`.
- **B. Scenario accuracy** — check the *verdict + category* on known injected defects (uses
  the reference test bed in `fevm_ps_dr_us_east_2_catalog`; on another workspace, map each
  row to the equivalent table in your own recon).

---

## 0. Preconditions

- The `rca-recon` skill is deployed to the workspace (`./sync_skill.sh <profile>`), and
  auto-discovered in **Genie Code → Agent mode**.
- `skill/rca-recon/config.yml` points `recon_catalog` / `recon_schema` / `dialect` /
  `warehouse_id` at the workspace under test.
- The tester has `SELECT` on the recon output schema **and** the source/target tables.
- A `recon_id` to analyze. To list them, ask Genie: *"List recent reconcile runs."* or run
  `python -m rca_engine.cli --list --recon-catalog <cat> --recon-schema <schema> --warehouse-id <wid> --profile <p>`.

### Reference recon runs (test bed workspace)
| recon_id | Pairs | With diffs | Use for |
|---|--:|--:|---|
| `eedae7b85e034c63b6b5fa96e1d044e5` | 16 | 14 | richest — full functional + edge scenarios |
| `e8330139f4144001a5ba218ba0689b28` | 9 | 8 | comprehensive |
| `0fe6053f134846948490952e94b747bf` | 6 | 5 | core pilot scenarios (S1–S10) |
| `4946c119b2c94d7ca514d1b3578e9798` | 4 | 3 | quick smoke test |
| `39c6a89f37e24fdeaa6b7c64453c05af` | 1 | 0 | ✅ clean path (zero findings) |

> Replace these with your own `recon_id`s when testing another workspace.

---

## A. Functional / behavioral test cases

| # | Objective | Prompt to Genie Code | Pass criteria |
|---|---|---|---|
| F1 | **Skill discovery** | `What skills do you have? Can you run root-cause analysis on a Lakebridge recon?` | The `rca-recon` skill is listed and offered. |
| F2 | **End-to-end RCA (happy path)** | `Use the rca-recon skill to run RCA on recon_id <ID_WITH_DIFFS>. Generate the notebook bundle, then run all cells.` | Produces an `rca_<id>/` bundle: `00_index.ipynb`, one notebook per table, `SUMMARY.md`, JSON. Cells execute without error. |
| F3 | **Human-in-the-loop approval gate** | (same as F2) | Before running cells, the skill **pauses and asks for approval**; it runs only after you confirm. |
| F4 | **Clean recon (no diffs)** | `Run RCA on recon_id 39c6a89f37e24fdeaa6b7c64453c05af.` | Reports **zero findings** / all-clean; does not fabricate issues. |
| F5 | **Single-table scope** | `Run RCA on recon_id <ID> but only for the <table> table.` | Analyzes just that one table pair; bundle/notebook scoped to it. |
| F6 | **Evidence discipline** | `For recon_id <ID>, show me one finding and the exact query that confirms it.` | Every concluded verdict cites an **executed confirming query** + result; nothing is a bare assertion. |
| F7 | **Verdict taxonomy present** | `Summarize recon_id <ID>: how many findings per verdict?` | Findings bucketed into 🔧 migration-induced / 📊 genuine-data / ✅ benign / 🔍 needs-review with counts. |
| F8 | **Suggested fixes + validation** | `Show the suggested fixes for recon_id <ID> and which are validated.` | Each fixable finding has a runnable fix; validated ones marked **✅ validated** (a query proved it closes the gap); others labelled *suggested*. |
| F9 | **Output location** | `Save the RCA notebooks for recon_id <ID> to <path>.` | Bundle written to the requested workspace folder / Volume; links returned. |
| F10 | **Systemic clusters & drift** | `For recon_id <ID>, what are the systemic root-cause clusters and any distribution drift?` | Renders 🧨 systemic clusters ("fix one, resolve many") and 📉 drift stats where applicable. |

---

## B. Scenario-accuracy test cases (verdict + category)

For the recon that includes each table, confirm the skill's verdict/category matches. Prompt
template:

> `Run RCA on recon_id <ID>. For <table>.<column>, tell me the category, the verdict, and the confirming query.`

### Core pilot (recon `0fe6053…`, source dialect `snowflake`)
| # | Table.Column | Expected category | Expected verdict |
|---|---|---|---|
| S1 | `fact_order_items.amount` | type_precision | 🔧 Migration-induced |
| S2 | `fact_orders.order_ts` | timezone | 🔧 Migration-induced (constant offset) |
| S3 | `dim_customer.attributes` | semi_structured | ✅ Benign / expected (JSON reorder) |
| S4 | `dim_product.sku` | string_format | 🔧 Migration-induced |
| S5 | `agg_daily_sales.revenue` | transpilation | 🔧 Migration-induced (rounding) |
| S6 | `fact_orders` (rows) | volume_missing | 🔧 Migration-induced (watermark) |
| S7 | `fact_order_items` (rows) | volume_extra | 🔧 Migration-induced (fan-out dupes) |
| S8 | `dim_customer.marketing_segment` | upstream_drift | 📊 Genuine data difference (stale) |
| S9 | `dim_customer.is_active` / `email` | null_boolean | 🔧 Migration-induced |
| S10 | `dim_customer.loyalty_tier` | upstream_drift | 📊 Genuine data difference (source never populated) |

### Edge cases (recon `eedae7…` / `e83301…`)
| # | Table.Column | Expected category | Expected verdict |
|---|---|---|---|
| E1 | `edge_numeric.v_double` | type_precision | 🔧 Migration-induced (double float error) |
| E2 | `edge_numeric.big_id` | type_precision | 🔧 Migration-induced (int overflow) |
| E3 | `edge_events.event_ts` | timezone | 🔍 **Needs review** (offset varies by row) |
| E4 | `edge_geo` (schema) | type_precision | 🔧 Migration-induced (rename + double) |
| E5 | `agg_weekly_sales.week_start` | env_config | 🔧 Migration-induced (week-start config) |
| E6 | `dim_supplier.contact_email` | upstream_drift | 📊 Genuine data difference |
| E7 | `dim_config.settings_json` | semi_structured | 🔍 **Needs review** (genuinely different JSON) |
| E8 | `fact_inventory.reorder_level` | null_boolean | 🔧 Migration-induced (NULL→-1) |
| E9 | `dim_flag.active_flag` | null_boolean | 🔧 Migration-induced (1/0→true/false) |
| E10 | `fact_payments` (rows) | volume_extra | 🔧 Migration-induced (non-idempotent merge) |
| E11 | `edge_string.name_ws` | string_format | 🔧 Migration-induced (trailing whitespace) |
| E12 | `edge_string.name_unicode` | string_format | 🔧 Migration-induced (Unicode NFC/NFD) |
| C1 | `dim_store` | — | — clean, **zero findings** |

**Key discriminators to verify** (these are the skill's differentiators):
- **S8/S10 & E6** are routed to the **data owner** (genuine), *not* flagged as migration bugs.
- **E3/E7** stay **needs-review** (evidence inconclusive) rather than being force-concluded.
- **S3** is **benign** (semantically equal JSON), not a defect.

---

## C. Robustness / negative test cases

| # | Objective | Prompt to Genie Code | Pass criteria |
|---|---|---|---|
| R1 | **Invalid recon_id** | `Run RCA on recon_id not-a-real-id.` | Fails gracefully with a clear message; no crash / no fabricated findings. |
| R2 | **Missing table permission** | Run against a recon whose source/target you lack `SELECT` on. | Confirming queries degrade gracefully; finding left **needs-review** with a note, pipeline continues. |
| R3 | **Pure data-driven (no scripts)** | `Run RCA on recon_id <ID>` with no code-aware inputs configured. | Works end-to-end without any source/target scripts (data-driven path). |
| R4 | **Dialect remediation** | Set `dialect` to your source (e.g. `oracle`), then `Run RCA on recon_id <ID>.` | Remediation text reflects the chosen source dialect's semantics. |
| R5 | **Tier-2 residual honesty** | `For recon_id <ID>, is anything still unexplained? What would confirm it?` | Unconfirmed items remain **needs-review** with a concrete next check — never promoted without a query. |

---

## D. Large-data / scan-scoping test cases

| # | Objective | Setup / Prompt | Pass criteria |
|---|---|---|---|
| P1 | **Key-scoped confirms (default)** | `config.yml`: `scan_mode: scoped`. `Run RCA on recon_id <ID> and show the confirming query for one column finding.` | Confirming query is bounded to flagged keys (`... IN (...)`); evidence is annotated **`[scoped to flagged keys]`**; the reported total mismatch count still matches recon metrics. |
| P2 | **Partition window** | `config.yml`: set `scan_partition_column` + `scan_date_start`/`_end` (a column on both sides). Re-sync, then run. | Drift/volume aggregates include a `... BETWEEN <start> AND <end>` filter (reads one window, not full history). |
| P3 | **Full mode** | `config.yml`: `scan_mode: full`. Run. | Queries have no `IN (...)`/`BETWEEN` bounding (baseline behavior); results consistent with P1's verdicts. |

---

## E. feature test cases

| # | Objective | Setup / Prompt | Pass criteria |
|---|---|---|---|
| O1 | **Code-aware RCA (scripts)** | Provide `source_scripts_dir` + `transpiled_output_dir` (or a `tables:` manifest). `Run RCA on recon_id <ID>; use the source & target SQL to explain the transpilation finding.` | Findings cite the **declared source type / transpiled derivation** (e.g. S5 rounding, S1 scale) from the SQL, not data alone. |
| O2 | **UC lineage / blast radius** | `config.yml`: `use_uc_lineage: true`. Run. | Findings show upstream provenance, a depth-agnostic **trace-back** to the root layer (see section L), and a 💥 downstream blast-radius table (or degrade cleanly if lineage absent). |
| O3 | **Learning loop (memory)** | `config.yml`: `use_memory: true`. Run the same recon twice. | Second run shows a **learned prior** proposing the recurring cause (still confirmed by a query, never on memory alone). |
| O4 | **Audit trail** | `config.yml`: audit enabled. Run. | A row per reconcile/RCA step is appended to the audit table (grouped by `run_id`). |

---

## L. Upstream lineage trace-back (depth-agnostic)

Scenario: the target we reconcile is fed by an arbitrarily deep pipeline —
`raw → … → staging/transform → target` (any number of layers). The defect is introduced
**somewhere upstream** (e.g. a bad `ROUND`/`CAST`/join in an intermediate transform), and
reconciliation runs on the final target. The skill should walk lineage **all the way back to
the root layer** — however many hops that is — and point the investigation at the layer where
the difference entered, rather than only the reconciled target.

> **How it works (read before running):** with `use_uc_lineage: true`, the deterministic pass
> walks UC lineage **hop by hop to the roots** (column lineage where a column is known, table
> lineage otherwise), bounded by `max_lineage_hops` (default 10, a safety budget — it stops
> early at the roots). Each finding gets a **`Lineage trace-back (N hops to root …)`** evidence
> line with the full path. Where lineage is missing/broken, the **Tier-2 LLM (Genie Code)
> fallback** continues the walk by proposing and executing confirming queries at each upstream
> layer. Requires captured UC lineage for the tables on the path + query access.

| # | Objective | Setup / Prompt | Pass criteria |
|---|---|---|---|
| L1 | **Direct upstream surfaced** | `use_uc_lineage: true`. `Run RCA on recon_id <ID>. For <target>.<column>, show its upstream lineage.` | Finding cites `column derives from <parent_table>.<col>` (UC column lineage); volume findings list the upstream table(s) feeding the target. |
| L2 | **Full trace-back to the root** | Same run. | A **`Lineage trace-back`** evidence line shows the complete path `target ← … ← root` with the correct **hop count**, and names the root layer. Depth is *not* fixed to 3 — it matches the real pipeline depth (bounded only by `max_lineage_hops`). |
| L3 | **Provenance-surprise flag** | On a column whose value comes from a table other than the reconciled source. | Evidence flags *"sourced from `<table>`, not the reconciled source — check for an unexpected join/derivation."* |
| L4 | **Confirm the layer with the bug** | `For recon_id <ID>, the mismatch on <target>.<column> — which upstream layer did the difference enter at? Walk the lineage back and confirm with a query.` | The engine/LLM identifies the offending upstream layer and **executes a query** comparing that layer's value to the expected value; verdict promoted only on confirmation, else stays needs-review with the upstream check as the next step. |
| L5 | **Depth budget honored** | Set `max_lineage_hops: 2` on a deeper pipeline; re-run. | Trace-back is marked **budget-truncated** (with a hint to raise `max_lineage_hops`); no crash, no infinite loop on cyclic lineage. |
| L6 | **Blast radius from the buggy layer** | Same run. | If the target feeds further consumers, a 💥 blast-radius note lists them so the upstream fix can be re-validated downstream. |

**Test bed (now provided):** deploy [`migration/multilayer/50_multilayer_pipeline.sql`](../migration/multilayer/50_multilayer_pipeline.sql)
— a medallion pipeline `sales_raw → sales_stg (⚠ defect) → sales_curated → sales_gold` where
`amount` is rounded to whole units **2 layers upstream** of the reconciled target (its
immediate parent `sales_curated` is a clean passthrough, so the walk must go past the first
hop). Reconcile with [`migration/recon/34_reconcile_config_multilayer.json`](../migration/recon/34_reconcile_config_multilayer.json)
(`sales_src` → `sales_gold`) to get a `recon_id`, then run RCA with `use_uc_lineage: true`.
Expected: `sales_gold.amount` → `transpilation` / 🔧 migration-induced, with
`Lineage trace-back (3 hops to root sales_raw): sales_gold.amount ← sales_curated.amount ←
sales_stg.amount ← sales_raw.amount` pointing at `sales_stg`; `sales_gold.qty` stays clean.
Score it automatically:

```bash
python scripts/validate_scenarios.py --recon-id <multilayer_recon_id> \
  --warehouse-id <WID> --recon-schema reconcile \
  --scenarios migration/multilayer/scenarios_multilayer.yaml --use-lineage
```

Full setup + expected oracle: [`migration/multilayer/README.md`](../migration/multilayer/README.md).
UC lineage is populated asynchronously — allow a few minutes after deploying before the
trace-back has data.

---

## Reporting template (per case)

```
Case:            <ID>
recon_id:        <id>
Prompt used:     <verbatim>
Observed:        <what happened / verdict / query>
Expected:        <from this plan>
Result:          PASS / FAIL
Notes / evidence:<links to the generated notebook, screenshots, query results>
```

For the scenario cases (B), the machine oracle is `migration/scenarios.yaml`; the harness
`python scripts/validate_scenarios.py --recon-id <id> --warehouse-id <wid>` checks them
automatically and is the fastest way to score section B in bulk.
