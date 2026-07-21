# One-Pager 2 — The Global Asset: The "To-Be" Package

**Goal:** Transition the localized post-reconciliation RCA solution into a **plug-and-play global
accelerator** any migration team can point at any reconciliation run — any source dialect, any
workspace — and get a signed-off RCA in minutes.
**Owner:** _[team / DRI]_ · **Date:** _[date]_

---

## 1. Vision
One versioned, self-service Genie Code skill in a shared catalog. A field engineer or migration
team installs it, sets a few config values, passes a `recon_id`, and gets the same evidence-first
RCA the current project produces — with the dialect, workspace, and scenario coupling removed.

## 2. Decoupling strategy (localized → general)
The engine is already source-agnostic at its core; the To-Be work makes every environment-specific
input a **swappable plug**:

| Coupling today (As-Is) | Decoupled interface (To-Be) |
|---|---|
| Fixed catalog/schemas/warehouse | **All config-driven** in `config.yml`; auto-resolve user home; no hard-coded IDs |
| Snowflake KB wired as default | **Dialect-pluggable knowledge base** (`snowflake.yaml`, `oracle.yaml`, `teradata.yaml`, `mssql.yaml`, …) selected by `dialect` |
| Source simulated as a schema | **Backend-agnostic `QueryRunner`** (Spark in-notebook / Statement API / Federation) |
| Probes hard-wired | **Probe registry** — add a probe without touching the classifier |
| Folder-scan for scripts | **Per-table manifest** (`tables:`) mapping each table to its own source/target script |
| Single project's tables | **Scenario oracle + test-bed generator** reusable as a per-dialect conformance suite |

## 3. Plug-and-play interfaces (the contract)
**Required input (1):** `recon_id`.

**Config contract (`config.yml`):**
- `recon_catalog`, `recon_schema` — where Lakebridge writes recon output.
- `dialect` — selects the knowledge base.
- `output_dir` — where the RCA notebook lands (bare name → user home; absolute → UC Volume/Workspace).
- `warehouse_id` — optional (local/CLI runs).

**Optional code-aware hooks (each simply adds confirmation):**
- `recon_config_path` (the mapping), `transpiled_output_dir` (target scripts),
  `source_scripts_dir` (declared source types), `transpile_error_file`, `use_uc_lineage`.

**Output contract:**
- RCA **notebook** (human) + **JSON** (machine-readable) → feeds dashboards, tickets, scorecards.
- Stable schema: findings with `category`, `verdict`, `confidence`, `evidence`, `owner`.

## 4. Generalizing for multiple scenarios
- **Dialect packs** — ship a KB + conformance scenarios per source EDW; onboarding a new source =
  add a YAML pack, no engine change.
- **Reusable conformance suite** — `scenarios.yaml` + the test-bed generator become a template each
  team clones to prove the accelerator on their own tables before a customer run.
- **Extensible evidence** — new sources (additional lineage, DQ tools, catalog metadata) attach as
  labeled evidence without changing verdict logic.

## 5. Packaging & distribution
- **Versioned skill** published to a shared skills catalog / internal marketplace (semver).
- **CI gate** — `pytest` (deterministic) + integration harness vs oracle on every change.
- **Install path** — one command / marketplace install; engine vendored, zero external installs.
- **Docs** — SKILL.md (contract, examples, edge cases) + these one-pagers + a quick-start.

## 6. Roadmap (indicative)
| Phase | Outcome |
|---|---|
| **P0 – Harden (now)** | Config-drive all anchors; publish skill v1; CI gate green |
| **P1 – Dialects** | Add Oracle/Teradata/MSSQL KB + conformance packs |
| **P2 – Distribution** | Marketplace listing, install docs, first external pilot + measured baselines |
| **P3 – Ecosystem** | Downstream: auto-file fix tickets, RCA scorecard dashboard, feedback loop into KB |

## 7. Success criteria
- Installed and run by a team **other than the authors** with no code changes.
- New source dialect onboarded via a **YAML pack only**.
- Pilot confirms the One-Pager 1 baselines (latency, coverage, variance) with **measured** numbers.

## 8. Bottom line
Same evidence-first RCA, now a self-service, dialect-pluggable, config-driven accelerator with a
clean input/output contract and a CI-backed conformance suite — ready for global reuse.
