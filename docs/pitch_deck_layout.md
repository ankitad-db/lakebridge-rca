# Pitch Deck Layout — RCA Reconciliation Accelerator

**Format:** 7 slides, ~10-min pitch. Keep each slide to one idea + one visual.
**Design cue:** dark Databricks-style theme; use the report's symbols (🔧 migration, 📊 genuine,
✅ benign, 🔍 needs-review) as a consistent visual language.

---

## Personas (referenced throughout)
| Persona | Cares about | Uses the accelerator to… |
|---|---|---|
| 🧑‍💻 **Migration / Data Engineer** | Fixing defects fast | Act on 🔧 migration-induced findings + exact remediation |
| 🗄️ **Data Owner / Source Team** | Not owning others' bugs | Receive only 📊 genuine data differences, correctly routed |
| 🧭 **Migration / Delivery Lead (PM)** | Go/no-go, status | Read TL;DR + match-rate scorecard for cutover decisions |
| 🏗️ **SA / Field Engineer (Databricks)** | Repeatable customer delivery | Install the skill, point at a `recon_id`, deliver RCA |
| 🔎 **Reconciliation / QA Analyst** | Trust & auditability | Validate with date-range widgets + cited evidence |
| 💼 **Exec Sponsor** | Time & risk reduction | See days → minutes, deterministic, evidence-backed |

---

## Slide 1 — Title / Value Prop
- **Title:** "From Mismatch to Root Cause in Minutes — RCA Accelerator for Migration Reconciliation"
- **Subline:** Lakebridge finds *what* differs. We answer *why* — and *who* should fix it.
- Logos/footer: team, date.
- 🎤 _Note:_ Reconciliation is table stakes; RCA is where the time goes. We automated it.

## Slide 2 — The Problem
- After a Snowflake→Databricks migration, reconcile flags thousands of row/column mismatches.
- RCA today is **manual, slow (days), inconsistent** (verdict depends on the analyst), and
  **mis-attributes** genuine data differences as migration bugs (and vice-versa).
- Visual: a wall of red mismatches → a confused analyst.
- 🎤 _Personas:_ the Engineer drowns in diffs; the Lead can't call go/no-go; the Data Owner gets
  blamed for migration bugs.

## Slide 3 — The Solution
- A **Genie Code skill**: pass one `recon_id` → a **live, evidence-first RCA notebook** in minutes.
- Every finding gets a **verdict**: 🔧 migration-induced · 📊 genuine data · ✅ benign · 🔍 needs-review.
- **Code-aware + cross-confirmed**: each finding cites up to **5 independent sources**
  (recon data + target code + source types + UC lineage + a live query).
- Visual: `recon_id → skill → RCA notebook (TL;DR + verdicts + fixes)`.

## Slide 4 — How It Works + Who Uses It
- Flow (left→right): **Lakebridge reconcile → RCA skill (ingest → classify → live drill-down) →
  RCA notebook + JSON**, with a **human approval gate** before auto-run.
- Overlay personas at the output: 🧑‍💻 Engineer (fixes), 🗄️ Data Owner (routed genuine diffs),
  🧭 Lead (scorecard), 🔎 Analyst (date-range validation).
- 🎤 _Note:_ same run, one artifact, each persona reads their slice.

## Slide 5 — Value / Proof
- Headline metrics (mark estimates until pilot): **days → < 30 min**, **deterministic verdicts**,
  **12 categories / 22 conformance scenarios**, **100% findings cite an executed query**.
- Trust: **55 deterministic tests + integration harness** vs a ground-truth oracle.
- Visual: before/after bar (latency) + a coverage matrix.

## Slide 6 — As-Is → To-Be (Localized → Global)
- Two columns: **As-Is** (works today, some workspace/dialect coupling) → **To-Be**
  (config-driven, dialect-pluggable KB, backend-agnostic runner, marketplace-published, CI-gated).
- One line: "Same evidence-first RCA — now plug-and-play for any source, any workspace."
- 🎤 _Persona:_ the Field Engineer installs once and reuses across customers.

## Slide 7 — The Ask / Next Steps
- **Ask:** endorse the two one-pagers + resource the global-asset roadmap (P1 dialects, P2 pilot).
- **Next steps:** (1) first customer pilot to lock measured baselines; (2) Oracle/Teradata dialect
  packs; (3) publish skill v1 to the shared catalog.
- Contact / owners.

---

## Optional appendix (only if asked)
- A1: Verdict taxonomy + edge cases (from One-Pager 1 §5).
- A2: Example RCA notebook screenshot (TL;DR + a confirmed finding with its query).
- A3: config.yml contract (from One-Pager 2 §3).
