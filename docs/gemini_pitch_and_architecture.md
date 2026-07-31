# ReconResolve — Pitch & Architecture Deck (Gemini input)

> **How to use this file:** Paste the whole document into **Gemini in Google Slides**
> ("Create a presentation from my notes / outline"). Generate **one slide per `## Slide`
> section**, using the **title**, the **bullets** (keep them short on-slide), and put the
> **Notes:** text into the slide's speaker notes. Render each **Diagram:** block as a
> left‑to‑right flow / SmartArt graphic. Apply the **Brand system** below to every slide.

## Brand system (Databricks — apply to all slides)

**Theme:** professional **Databricks dark** theme, consistent on every slide. Generous white
space, one idea per slide, large headline, short bullets, a single focal visual. Avoid clip-art,
gradients-on-text, and busy backgrounds.

**Color palette (use these exact hex values):**

| Role | Color | Hex |
|---|---|---|
| Primary brand / accent | **Databricks Lava** | `#FF3621` |
| Brand dark (headers, deep bg) | **Databricks Navy** | `#1B3139` |
| Slide background | Near-black navy | `#0B0F14` |
| Card / panel surface | Slate | `#131C24` |
| Card border / hairline | Steel | `#2A3742` |
| Primary text (on dark) | Off-white | `#E8ECEF` |
| Secondary / muted text | Cool gray | `#8A94A6` |
| Info accent | Blue | `#2272B4` |
| Success accent | Green | `#00A972` |
| Warning accent | Amber | `#FFAB00` |
| Alert / critical | Maroon | `#98102A` |

**Verdict color language (use consistently wherever verdicts appear):**
🔧 **Migration-induced** = Lava `#FF3621` · 📊 **Genuine data** = Blue `#2272B4` ·
✅ **Benign** = Green `#00A972` · 🔍 **Needs review** = Amber `#FFAB00`.

**Typography:** Headings **DM Sans** (or Poppins/Montserrat) semi-bold; body **Inter** (or Roboto/Arial).
Title 34–40pt, section headers 24–28pt, body 16–18pt, notes 12pt. Left-aligned. Tight heading
letter-spacing.

**Layout / master:** thin Lava top-rule or a small Lava square logo mark top-left; slide title
top-left; footer in muted gray: `ReconResolve · Post-Lakebridge RCA on Databricks` + page number.
Diagrams: rounded-rectangle nodes on card surface, steel borders, Lava arrows, per-stage accent
tints (Sources = blue, Reconcile = amber, RCA engine = lava, Outputs = green). Keep icons flat and
monochrome; the four verdict emojis are the only "color pops" in body text.

---

## Slide 1 — Title

- **ReconResolve**
- **From reconciliation mismatch to confident root cause — automatically.**
- Post-migration Root-Cause Analysis for **Lakebridge** data migrations to Databricks.
- Footer: your name/team · date · "Built on Databricks · Genie Code skill + Databricks App"

Notes: Lakebridge tells you *what* differs after a migration. ReconResolve answers *why* it differs, whether it's a migration bug or real data, how to fix it, and who owns it — in minutes, with evidence.

---

## Slide 2 — The problem

- A warehouse migration (Snowflake / Oracle / Teradata / SQL Server / Synapse → Databricks) ends with **reconcile flagging thousands of row & column mismatches**.
- Root-cause analysis today is **manual, slow (days), and inconsistent** — the verdict depends on which analyst looked.
- Worst failure mode: **mis-attribution** — genuine source-data differences get filed as migration bugs (and vice-versa), so the wrong team gets paged.
- Reconciliation is table stakes; **RCA is where the time and the arguments go.**

Notes: Engineers drown in diffs, the delivery lead can't call go/no-go, and the data owner gets blamed for migration defects they didn't cause.

---

## Slide 3 — The solution

- **ReconResolve** turns a reconcile result into a finished root-cause analysis, two ways:
  - **⚡ Trigger** a reconcile from tables (auto-detects join keys) **→ or** start from an existing `recon_id`.
  - **🔬 Analyze** every mismatch with deterministic probes + a **live confirming query**.
- Each finding gets a **verdict + fix + owner**: 🔧 migration-induced · 📊 genuine data · ✅ benign · 🔍 needs-review.
- **Evidence-first:** every verdict cites a query that actually ran (up to 5 independent sources).
- Delivered as **both** a **Genie Code skill** (agentic, in-notebook) **and** a **Databricks App** (self-serve UI).

Notes: The differentiator is deterministic, evidence-backed verdicts — Genie Code (the LLM) drives the workflow agentically, but the verdict itself comes from typed probes + a live confirming query + the knowledge base, not from a free-form model opinion — plus the migration-vs-genuine-data distinction that routes work to the right team.

---

## Slide 3b — Our solution (two-card layout)

> Layout: eyebrow + big title + one-line subtitle, then **two equal rounded-corner cards** side by
> side. **Left card** = light surface `#F9F7F4`, dark Navy text, a small filled Navy square before
> the header. **Right card** = Navy `#1B3139` surface, white text, with a large **amber `#FFAB00`**
> headline. Small Lava `#FF3621` rule above the eyebrow.

- **Eyebrow:** OUR SOLUTION — LAKEBRIDGE'S MISSING 4TH STAGE
- **Title:** ReconResolve
- **Subtitle:** Lakebridge does **Analyze → Transpile → Reconcile**. **ReconResolve** adds the next stage — **Resolve**: take the `recon_id` and turn every flagged mismatch into a **root cause, a fix, and an owner**. Delivered as a **Genie Code skill + Databricks App**.

> Optional top strip above the two cards: a 4-chip pipeline — `Analyze` · `Transpile` · `Reconcile`
> (muted/steel, "Lakebridge") **→** `Resolve` (Lava `#FF3621`, "ReconResolve"), with the last chip
> highlighted to show we own the new stage.

**▪ How it works** *(left card)*
- **Starts where Lakebridge Reconcile stops** — picks up a `recon_id` (or triggers the reconcile itself, auto-detecting join keys)
- **Ingests** recon `details` → runs **deterministic typed probes** per mismatch (numeric · timezone · null/boolean · string · volume · semi-structured)
- **Confirms** each cause with a **live query** + a per-dialect knowledge base (Snowflake, Oracle, Teradata, SQL Server, Synapse)
- **Genie Code fallback** traces the leftovers back through the **transpiled SQL + UC lineage** to pinpoint the cause — and still proves it with a query
- **Publishes** verdict + fix + owner + a runnable RCA notebook — via one **Genie Code skill**

**◻ Productivity impact** *(right card — dark surface, amber hero metric)*
- ## Hours → minutes
- **Deterministic, evidence-backed** verdicts — Genie Code **orchestrates**, but every verdict is **proven by a live query**
- Routes 🔧 migration bugs vs 📊 genuine data differences to the **right team**
- Every step in an **audit trail**; every verdict is backed by an executed query

Notes: Same two-card pattern as the reference — left **"How it works"**, right **"Productivity impact"** with the amber **"Hours → minutes"** hero metric (an estimate until pilot baselines). The unique keywords (post-reconcile Resolve stage, deterministic-first + Genie Code fallback with code/lineage trace-back, migration-bug-vs-genuine-data verdict) ride in the bullets so the format matches the one you shared while the messaging stays sharp and accurate.

---

## Slide 4 — Who it's for (personas)

- 🧑‍💻 **Migration / Data Engineer** — acts on 🔧 findings with exact remediation.
- 🗄️ **Data Owner / Source team** — receives only 📊 genuine data differences, correctly routed.
- 🧭 **Delivery / Migration Lead** — reads the TL;DR + match-rate scorecard for go/no-go.
- 🏗️ **Databricks SA / Field Engineer** — installs once, reuses across customers.
- 🔎 **Reconciliation / QA Analyst** — validates with date-range widgets + cited evidence.
- 💼 **Exec Sponsor** — sees days → minutes, deterministic, auditable.

Notes: One run, one set of artifacts — each persona reads their own slice.

---

## Slide 5 — How it works (data flow)

Diagram (left → right, 4 stages with arrows between; add a return arrow from stage 4 back to stage 2 labeled "fix & re-run"):

1. **🗄️ Sources** — Source EDW (Snowflake / Oracle / Teradata / SQL Server / Synapse) · Databricks target · *(optional)* source + transpiled SQL scripts
2. **🔁 Reconcile** — Lakebridge reconcile *or* app-native reconcile (auto-detect join keys) → `recon_id` + `main` / `metrics` / `details`
3. **🔬 RCA engine** — Ingest → **Tier 1 (deterministic):** Probes (numeric · temporal · null · string · semi-structured) → Classify (+ knowledge base · sqlglot · UC lineage) → Live drill-down (one confirming query per finding) → **Tier 2 (LLM fallback):** Genie Code reasons over the residual `needs-review`/`unknown` findings and proposes a confirming query — **promoted only if the query confirms**
4. **🎯 Outputs** — Verdicts · 📊 Run dashboard · 📓 Runnable notebooks · 🧾 Audit trail

- **Feedback loop:** 🔧 findings tell the engineer exactly what to fix, then re-reconcile to confirm the diff is gone.

Colors: Sources = blue `#2272B4` tint · Reconcile = amber `#FFAB00` tint · RCA engine = Lava `#FF3621` tint · Outputs = green `#00A972` tint; connector arrows in Lava `#FF3621` on `#0B0F14`.

Notes: Two tiers. Tier 1 is deterministic and typed — each probe explains a specific mechanism (scale loss, timezone shift, null/boolean encoding, string normalization, volume gap), then a live query confirms it before a verdict is set. Tier 2 is the LLM (Genie Code) fallback that only fires on the residual findings the rules couldn't conclude: it reasons over the evidence bundle and proposes a confirming query, but the verdict is promoted **only if that query confirms** — so the LLM widens coverage on the long tail without ever guessing a verdict.

---

## Slide 6 — The verdict taxonomy (the field humans act on)

- 🔧 **Migration-induced** — fix in the migration (type mapping, timezone, transpiled SQL, null/boolean). → Migration engineer.
- 📊 **Genuine data difference** — the source/upstream data really differs. → Data owner. **Not a migration bug.**
- ✅ **Benign / expected** — semantically-equal representation (e.g. JSON key order) or within tolerance. → No action.
- 🔍 **Needs review** — evidence inconclusive; states exactly what to check next.

Notes: Separating "technical category" from "who should act" is the core idea — it stops migration teams and data owners from throwing tickets over the wall.

---

## Slide 7 — Source-agnostic by design

- **Not a Snowflake-only tool.** Works for **any Lakebridge-supported source** migrating to Databricks.
- The engine is **dialect-driven**: it loads a per-dialect **knowledge base** (type mappings, risky functions, remediation).
- Knowledge bases ship for **Snowflake, Oracle, Teradata, SQL Server (mssql), Synapse** — pick the source dialect in the UI.
- Unknown dialects still run with generic probes; adding a source = one `<dialect>.yaml` file.
- **Snowflake is our tested reference bed** (retail migration: 6 pilot + 10 edge-case tables, 22 calibrated scenarios).

Notes: Oracle example verified live — analyzing as `oracle` yields Oracle-specific remediation ("empty-string = NULL, NVL/DECODE semantics…"), proving the dialect knob flows end-to-end.

---

## Slide 8 — Architecture (technical)

Diagram (three layers, top to bottom):

- **Surfaces (2):** **Genie Code skill** (`SKILL.md` + `scripts/run_rca.py`, runs in a Databricks notebook) · **Databricks App** (FastAPI + React, service-principal auth, live URL).
- **Shared engine (`rca_engine`, pure Python behind a `QueryRunner` protocol):**
  `discovery` · `ingest` · `probes` · `classify` (+ `knowledge/*.yaml`, `codecorr`/sqlglot, UC lineage) · `reconcile` (app-native) · `report` (notebooks + SUMMARY) · `audit`.
- **Data plane (Unity Catalog):** source & target tables · `reconcile.main/metrics/details` · `rca_genie_audit` (Delta) · published notebooks in `/Workspace`.

- **Backend-agnostic:** same engine runs on a notebook **Spark** session or the **SQL Statement Execution API** (in-app), so no rewrite between surfaces.

Colors: Surfaces layer = Lava `#FF3621` header · Engine layer = Navy `#1B3139` cards with steel `#2A3742` borders · Data-plane layer = blue `#2272B4` accent. Three stacked bands on `#0B0F14`.

Notes: The engine is a library; both the skill and the app are thin wrappers. That's why one codebase powers the agentic path and the self-serve UI.

---

## Slide 9 — The Databricks App

- **Live, self-serve UI** (Databricks-themed) — no notebook required.
- **Overview** (data-flow home) · **⚡ Trigger recon** · **📥 Recon runs** · **📊 Run dashboard** · **🔬 Analyze table-by-table** · **🔎 Table drill-down** · **🧾 Audit trail**.
- **Catalog & source-dialect pickers** in the sidebar — switch data source and dialect on the fly.
- **Trigger → reconcile → RCA → notebooks** end-to-end, with auto join-key detection and per-pair isolation.
- Runs as a **service principal** honoring Unity Catalog permissions; publishes runnable notebooks to the workspace.

Notes: The app broadens the audience beyond notebook users — delivery leads, data owners, and execs get a click-through dashboard and a severity scorecard.

---

## Slide 10 — The Genie Code skill

- One skill covers **both steps**: `tables → reconcile → RCA`, **or** RCA directly from a `recon_id`.
- Runs **live in the workspace**: generates a notebook, executes drill-down queries, refines hypotheses.
- **Two-tier RCA:** deterministic engine first; the LLM (Genie Code) is the **fallback** for the residual `needs-review`/`unknown` findings — it proposes a cause **plus a confirming query**, and a verdict is promoted **only if the query confirms** (never a bare LLM guess).
- **Human-in-the-loop:** pauses for approval before running all cells; reconciles the written verdicts against the executed outputs.
- **Code-aware (optional):** point it at source + transpiled SQL scripts and it confirms causes from the actual translated code (sqlglot) + UC lineage.
- Open **Agent Skills standard** (`SKILL.md`) — install once, reuse across engagements.

Notes: The skill is the agentic/interactive path; the app is the at-a-glance path. Same engine, same verdicts.

---

## Slide 11 — Audit & trust

- **Append-only audit trail** (Delta): every reconcile & RCA step logs one row — *what ran, when, by whom, scope, outcome, notebook* — grouped by a `run_id`.
- Shared by **app, skill, and CLI** → one history across every surface.
- **Every verdict cites an executed query** (up to 5 independent evidence sources per finding).
- **83 automated tests** + a scenario oracle (22 calibrated scenarios) guard the engine.

Notes: Deterministic + auditable is the trust story: nothing is a black box, and you can prove why each call was made.

---

## Slide 12 — Value / proof

- ⏱️ **Days → minutes** for a full-run RCA (estimate; locking with pilot baselines).
- 🎯 **Deterministic, consistent verdicts** — LLM-orchestrated but evidence-verified; each verdict is backed by an executed query, not a free-form guess.
- 🧪 **12 root-cause categories**, **22 conformance scenarios**, **100% of findings cite a query**.
- 🔁 **Closed loop:** fix → re-reconcile → confirm the diff cleared.
- 🌐 **Multi-source & multi-workspace:** dialect-pluggable, catalog-selectable, deployed as a live app.

Notes: Mark latency numbers as estimates until the first customer pilot; everything else is built and verified today.

---

## Slide 13 — As-Is → To-Be

- **As-Is (today):** engine + skill + live app; multi-dialect KBs (5 sources); app-native reconcile with auto-key detection; audit trail; verified on a Snowflake test bed.
- **To-Be (roadmap):**
  - More dialect packs (Redshift, BigQuery, Netezza, Db2) + per-dialect edge-case test beds.
  - Run-over-run **regression tracking** (did last cutover's fixes clear the findings?).
  - **Auto-remediation** — propose migration-SQL patches for 🔧 findings as a reviewable diff.
  - **Routing integrations** — push 📊 diffs to data owners via Slack/Jira with the summary attached.

Notes: Each roadmap item is independent and builds on the decoupled engine — no rewrites required.

---

## Slide 14 — The ask / next steps

- **Ask:** endorse ReconResolve as the standard post-Lakebridge RCA accelerator for migrations.
- **Next steps:**
  1. First **customer pilot** to lock measured baselines (latency, accuracy).
  2. Add **Oracle / Teradata** edge-case test beds to regression-test those KBs.
  3. Publish the skill to the shared catalog + share the app URL with the field.
- Contact / owners.

Notes: We already have a live app and a working skill; the pilot converts estimates into measured proof and prioritizes the next dialect packs.

---

## Appendix A — Reference (optional slides)

- **A1 — Verdict + evidence example:** one finding with its category, confidence, remediation, owner, and the confirming SQL query + result.
- **A2 — Component map:** `rca_engine` modules (discovery, ingest, probes, classify, reconcile, report, audit, knowledge) and how the skill vs app call them.
- **A3 — Config contract:** `config.yml` (skill) / `app.yaml` env — catalog, schema, dialect, warehouse, notebook dir, audit table.
- **A4 — Screens:** Overview data-flow, Trigger recon, Run dashboard scorecard, Table drill-down, Audit trail.
