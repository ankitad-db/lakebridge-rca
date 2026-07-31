import { Fragment, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getActiveCatalog } from "../api";
import type { AppConfig } from "../types";

/* --------------------------------------------------------------------------- */
/* Process-flow model — the "how it works" pipeline, one card per stage.        */
/* Each stage is clickable and drives the live detail panel below.              */
/* --------------------------------------------------------------------------- */
type Stage = {
  id: string;
  accent: "blue" | "amber" | "lava" | "violet" | "green";
  ic: string;
  lbl: string;
  step: string;
  nodes: { n: string; s?: string; mono?: boolean; dashed?: boolean }[];
  detail: { does: string; inputs: string[]; outputs: string[]; runs: string; link?: { to: string; label: string } };
};

const STAGES: Stage[] = [
  {
    id: "sources", accent: "blue", ic: "🗄️", lbl: "Sources", step: "input",
    nodes: [
      { n: "Source EDW", s: "Snowflake · Oracle · Teradata · SQL Server · Synapse" },
      { n: "Databricks target", s: "migrated tables", mono: true },
      { n: "SQL scripts + recon config", s: "source & transpiled — optional, code-aware (skill path today)", dashed: true },
    ],
    detail: {
      does: "The inputs RCA reasons over: the original source warehouse, the migrated Databricks tables, and (optionally) the source + transpiled SQL and Lakebridge recon config for code-aware analysis.",
      inputs: ["Source EDW tables", "Databricks target tables", "(optional) source + transpiled SQL, recon config"],
      outputs: ["Table pairs to reconcile"],
      runs: "Any Lakebridge-supported source — Snowflake is the tested reference bed.",
    },
  },
  {
    id: "reconcile", accent: "amber", ic: "🔁", lbl: "Reconcile", step: "step 1",
    nodes: [
      { n: "Lakebridge reconcile", s: "or app-native reconcile" },
      { n: "Auto-detect join keys", s: "unique + non-null id-like cols" },
      { n: "recon_id + main / metrics / details", s: "Lakebridge-compatible Delta", mono: true },
    ],
    detail: {
      does: "Compares each source↔target pair and writes Lakebridge-compatible main/metrics/details under a fresh recon_id. Join keys are auto-detected when not supplied; each pair is isolated so one failure never sinks the run.",
      inputs: ["Table pairs (source & target schema)"],
      outputs: ["recon_id", "main / metrics / details (Delta)"],
      runs: "App-native on the SQL warehouse, or Lakebridge reconcile.",
      link: { to: "/trigger", label: "⚡ Trigger a reconcile" },
    },
  },
  {
    id: "tier1", accent: "lava", ic: "🔬", lbl: "RCA · Tier 1 (deterministic)", step: "step 2",
    nodes: [
      { n: "Ingest", s: "read main / metrics / details" },
      { n: "Typed probes", s: "numeric · temporal · null · string · volume · semi-structured" },
      { n: "Classify", s: "+ knowledge base · sqlglot · UC lineage" },
      { n: "Live drill-down", s: "one confirming query per finding" },
    ],
    detail: {
      does: "The deterministic first pass: typed probes recognise known mismatch mechanisms, the knowledge base + transpiled code refine them, and a live confirming query is run per finding. No LLM — pure, explainable rules.",
      inputs: ["recon_id + details", "knowledge/<dialect>.yaml", "(optional, skill path today) source + transpiled SQL scripts → lakebridge.py, UC lineage"],
      outputs: ["Findings with verdict + confidence", "confirming query as evidence"],
      runs: "rca_engine — Spark in a notebook, or the SQL Statement API in the app.",
    },
  },
  {
    id: "tier2", accent: "violet", ic: "🧠", lbl: "RCA · Tier 2 (LLM fallback)", step: "step 3",
    nodes: [
      { n: "Residual findings only", s: "needs-review / unknown" },
      { n: "Genie Code / Foundation Model", s: "traces back via transpiled SQL + UC lineage" },
      { n: "Proposes cause + confirming query", s: "structured hypothesis" },
      { n: "Query-confirmed gate", s: "promoted only if the query agrees", mono: true },
    ],
    detail: {
      does: "Only the leftovers the rules could not conclude go to the LLM. It traces the mismatch back through the transpiled SQL and UC lineage, proposes a cause AND a confirming query — and the verdict is promoted only if that query confirms. Never a bare guess.",
      inputs: ["Residual needs-review / unknown findings", "evidence bundle (samples, source type, derivation, lineage)"],
      outputs: ["Query-confirmed verdict, or stays needs-review with the next check"],
      runs: "Genie Code skill (interactive) · Foundation Model API in the app (headless).",
    },
  },
  {
    id: "outputs", accent: "green", ic: "🎯", lbl: "Outputs", step: "result",
    nodes: [
      { n: "Verdicts", s: "🔧 migration · 📊 data · ✅ benign · 🔍 review" },
      { n: "📊 Run dashboard", s: "match %, severity, scorecard" },
      { n: "📓 Notebooks", s: "per-table + index, runnable in workspace" },
      { n: "🧾 Audit trail", s: "append-only Delta history" },
    ],
    detail: {
      does: "Every finding lands as a verdict with a fix and an owner, rendered in the dashboard, published as runnable per-table notebooks, and recorded in the audit trail.",
      inputs: ["Concluded findings"],
      outputs: ["Dashboard view", "RCA notebooks (workspace)", "SUMMARY.md", "audit rows"],
      runs: "App dashboard + workspace notebooks.",
      link: { to: "/runs", label: "📥 Browse recon runs" },
    },
  },
];

/* --------------------------------------------------------------------------- */
/* DFD model — external entities, processes, data stores + labelled flows.      */
/* --------------------------------------------------------------------------- */
type DfdNode = {
  id: string;
  kind: "entity" | "process" | "store";
  label: string;
  sub?: string;
  detail: string;
  inflows?: string[];
  outflows?: string[];
};

const DFD: DfdNode[] = [
  // External entities
  { id: "edw", kind: "entity", label: "Source EDW", sub: "Snowflake / Oracle / …", detail: "The origin warehouse being migrated. Read for provenance (is the source genuinely NULL/stale?).", outflows: ["source rows → 1.0"] },
  { id: "tgt", kind: "entity", label: "Databricks target", sub: "migrated tables", detail: "The migrated tables under test. Compared against the source and drilled into.", outflows: ["target rows → 1.0"] },
  { id: "scripts", kind: "entity", label: "SQL scripts + recon config", sub: "source & transpiled (optional · skill path today)", detail: "Original + transpiled SQL and the Lakebridge recon config. Parsed with sqlglot by rca_engine/lakebridge.py into declared source types + per-column transforms. Wired through the Genie Code skill today (config.yml → build_mapping); the app path does not ingest scripts yet.", outflows: ["derivations, types → 3.0"] },
  { id: "lineage", kind: "entity", label: "UC lineage", sub: "system.access.*_lineage", detail: "Unity Catalog column/table lineage — upstream columns & tables feeding the target.", outflows: ["upstreams → 3.0 / 5.0"] },
  { id: "fm", kind: "entity", label: "Foundation Model", sub: "serving endpoint", detail: "Databricks FM endpoint queried by the Tier-2 fallback to propose a cause + confirming query.", inflows: ["evidence bundle ← 5.0"], outflows: ["hypothesis + query → 5.0"] },
  // Processes
  { id: "p1", kind: "process", label: "1.0 Reconcile", detail: "Compare each pair (auto-detect keys); write recon_id + main/metrics/details.", inflows: ["source & target rows"], outflows: ["main/metrics/details → D1"] },
  { id: "p2", kind: "process", label: "2.0 Ingest", detail: "Normalise recon details into typed Findings + per-table summaries.", inflows: ["D1"], outflows: ["findings → 3.0"] },
  { id: "p3", kind: "process", label: "3.0 Probe & classify", detail: "Typed probes + knowledge base + code correlation → category, verdict, confidence.", inflows: ["findings", "D2 knowledge", "scripts, lineage"], outflows: ["hypotheses → 4.0"] },
  { id: "p4", kind: "process", label: "4.0 Live drill-down", detail: "Run one confirming query per finding against source/target; finalise the verdict.", inflows: ["hypotheses", "target/source"], outflows: ["confirmed findings → 5.0 / 6.0"] },
  { id: "p5", kind: "process", label: "5.0 LLM fallback (Tier 2)", detail: "Residual needs-review/unknown only: FM proposes cause + query; promote only if the query confirms.", inflows: ["residual findings", "FM hypothesis"], outflows: ["query-confirmed verdicts → 6.0"] },
  { id: "p6", kind: "process", label: "6.0 Report & publish", detail: "Render dashboard view, write SUMMARY.md + per-table notebooks to the workspace.", inflows: ["concluded findings"], outflows: ["bundle/notebooks → D3"] },
  { id: "p7", kind: "process", label: "7.0 Audit log", detail: "Append one row per reconcile/RCA step (who/when/scope/outcome/notebook), grouped by run_id.", inflows: ["step metadata"], outflows: ["row → D4"] },
  // Data stores
  { id: "d1", kind: "store", label: "D1 · recon.main/metrics/details", detail: "Lakebridge-compatible reconcile output for a recon_id.", inflows: ["← 1.0"], outflows: ["→ 2.0"] },
  { id: "d2", kind: "store", label: "D2 · knowledge/<dialect>.yaml", detail: "Per-dialect type mappings, risky functions, remediation.", outflows: ["→ 3.0"] },
  { id: "d3", kind: "store", label: "D3 · RCA bundle + notebooks", detail: "findings JSON, SUMMARY.md, per-table notebooks + index (workspace).", inflows: ["← 6.0"] },
  { id: "d4", kind: "store", label: "D4 · rca_genie_audit (Delta)", detail: "Append-only audit trail shared by app, skill, and CLI.", inflows: ["← 7.0"] },
];

const KIND_LABEL: Record<DfdNode["kind"], string> = {
  entity: "External entity", process: "Process", store: "Data store",
};

/* --------------------------------------------------------------------------- */
/* Detailed technical flowchart — decision-aware (yes/no, if/then, error &      */
/* feedback paths), each block annotated with the repo file(s) that run it.     */
/* --------------------------------------------------------------------------- */
type Branch = { cond: string; to: string; tone: "yes" | "no" | "loop" | "route" };
type FlowStep = {
  id: string;
  kind: "terminal" | "process" | "store" | "decision";
  n?: string;
  ic?: string;
  label: string;
  desc?: string;
  files?: string[];
  branches?: Branch[];
};

const DETAIL_STEPS: FlowStep[] = [
  { id: "start", kind: "terminal", label: "Start · migrated Databricks tables to validate", ic: "▶" },
  {
    id: "d-has-id", kind: "decision", label: "Already have a recon_id?",
    files: ["app/server/routes/api.py"],
    branches: [
      { cond: "YES", to: "Skip reconcile → jump straight to Ingest (step 5)", tone: "yes" },
      { cond: "NO", to: "Trigger a reconcile first (step 1)", tone: "no" },
    ],
  },
  {
    id: "p-trigger", kind: "process", n: "1", label: "Trigger reconcile (app-native or Lakebridge)",
    desc: "Compare each source↔target pair; each pair isolated so one failure never sinks the run.",
    files: ["rca_engine/reconcile.py", "rca_engine/lakebridge.py", "app/server/rca_service.py"],
  },
  {
    id: "d-keys", kind: "decision", label: "Join keys provided for the pair?",
    files: ["rca_engine/reconcile.py", "rca_engine/discovery.py"],
    branches: [
      { cond: "YES", to: "Use the supplied keys", tone: "yes" },
      { cond: "NO", to: "Auto-detect unique + non-null id-like columns (capped attempts)", tone: "no" },
    ],
  },
  {
    id: "d-keys-ok", kind: "decision", label: "Keys resolved within the attempt limit?",
    files: ["rca_engine/discovery.py"],
    branches: [
      { cond: "YES", to: "Reconcile the pair", tone: "yes" },
      { cond: "NO", to: "Mark pair failed · isolate · continue other pairs", tone: "no" },
    ],
  },
  {
    id: "s-recon", kind: "store", label: "D1 · write recon_id + main / metrics / details",
    desc: "Lakebridge-compatible Delta output for the run.",
    files: ["rca_engine/reconcile.py", "rca_engine/lakebridge.py"],
  },
  {
    id: "d-mismatch", kind: "decision", label: "Any mismatches in details?",
    files: ["rca_engine/ingest.py"],
    branches: [
      { cond: "NO", to: "Table clean ✅ 100% match → report as benign / clean", tone: "yes" },
      { cond: "YES", to: "Ingest findings → run RCA (step 5)", tone: "no" },
    ],
  },
  {
    id: "p-ingest", kind: "process", n: "5", label: "Ingest → typed Findings + per-table summaries",
    desc: "Normalise recon details (handles _null_recon_ etc.) into typed findings.",
    files: ["rca_engine/ingest.py", "rca_engine/models.py"],
  },
  {
    id: "p-classify", kind: "process", n: "6", label: "Tier 1 — typed probes + knowledge base + code correlation",
    desc: "Numeric · temporal · null/boolean · string · volume · semi-structured probes, refined by the per-dialect KB. If the source + transpiled SQL scripts are supplied (skill path today), lakebridge.py parses them with sqlglot into declared source types + per-column transforms, which codecorr.py correlates to confirm a transpilation cause.",
    files: ["rca_engine/classify.py", "rca_engine/probes/*.py", "rca_engine/knowledge/<dialect>.yaml", "rca_engine/lakebridge.py", "rca_engine/codecorr.py"],
  },
  {
    id: "d-known", kind: "decision", label: "Does a probe recognise a known mechanism?",
    files: ["rca_engine/classify.py"],
    branches: [
      { cond: "YES", to: "Form hypothesis + root-cause category", tone: "yes" },
      { cond: "NO", to: "Leave as needs_review / unknown", tone: "no" },
    ],
  },
  {
    id: "p-drill", kind: "process", n: "7", label: "Live drill-down — run one confirming query per finding",
    desc: "Aggregate query against the real source/target to prove the hypothesis.",
    files: ["rca_engine/drilldown.py"],
  },
  {
    id: "d-confirm", kind: "decision", label: "Does the query confirm the hypothesis?",
    files: ["rca_engine/drilldown.py", "rca_engine/severity.py"],
    branches: [
      { cond: "YES", to: "Verdict confirmed → 🔧 migration / 📊 genuine / ✅ benign", tone: "yes" },
      { cond: "NO", to: "Stays 🔍 needs_review", tone: "no" },
    ],
  },
  {
    id: "d-residual", kind: "decision", label: "Any residual needs_review / unknown left?",
    files: ["rca_engine/resolve.py"],
    branches: [
      { cond: "NO", to: "Skip Tier 2 → go to report (step 9)", tone: "yes" },
      { cond: "YES", to: "Escalate to Tier 2 LLM fallback (step 8)", tone: "no" },
    ],
  },
  {
    id: "p-llm", kind: "process", n: "8", label: "Tier 2 — Genie Code / Foundation Model fallback",
    desc: "The Genie Code skill agent (interactive) — or the app's FM endpoint (headless) — traces the mismatch back through transpiled SQL + UC lineage and proposes a cause AND a confirming query.",
    files: ["skill/rca-recon/scripts/run_rca.py", "app/server/llm_fallback.py", "rca_engine/resolve.py", "rca_engine/lineage.py"],
  },
  {
    id: "d-llm-confirm", kind: "decision", label: "Does the LLM's proposed query confirm?",
    files: ["rca_engine/resolve.py"],
    branches: [
      { cond: "YES", to: "Promote to confirmed verdict", tone: "yes" },
      { cond: "NO", to: "Keep needs_review + record the exact next check (never a bare guess)", tone: "no" },
    ],
  },
  {
    id: "p-report", kind: "process", n: "9", label: "Score severity → report → publish notebooks",
    desc: "Rank severity, render the dashboard view, write SUMMARY.md + per-table notebooks to the workspace.",
    files: ["rca_engine/severity.py", "rca_engine/report.py"],
  },
  {
    id: "s-bundle", kind: "store", label: "D3 · RCA bundle + per-table notebooks (workspace)",
    files: ["rca_engine/report.py"],
  },
  {
    id: "p-audit", kind: "process", label: "Audit log — append one row (best-effort, never blocks RCA)",
    desc: "Reconcile row + RCA row share a run_id; shared by app, skill, and CLI.",
    files: ["rca_engine/audit.py"],
  },
  {
    id: "d-route", kind: "decision", label: "Verdict routing & feedback loop",
    files: ["rca_engine/models.py"],
    branches: [
      { cond: "🔧 migration-induced", to: "Fix transpiled SQL / mapping → re-run reconcile (loop to step 1)", tone: "loop" },
      { cond: "📊 genuine data", to: "Route to the data owners", tone: "route" },
      { cond: "✅ benign", to: "Accept — expected difference", tone: "route" },
      { cond: "🔍 needs review", to: "Manual follow-up using the recorded next-check", tone: "route" },
    ],
  },
  { id: "end", kind: "terminal", label: "Done · every mismatch has a cause, a fix, and an owner", ic: "■" },
];

export function HomePage({ config }: { config: AppConfig | null }) {
  const nav = useNavigate();
  const catalog = getActiveCatalog() || config?.recon_catalog || "";
  const demo = config?.demo_mode;

  const [view, setView] = useState<"flow" | "dfd" | "detail">("flow");
  const [stageId, setStageId] = useState<string>("tier2");
  const [dfdId, setDfdId] = useState<string>("p5");
  const stage = STAGES.find((s) => s.id === stageId)!;
  const dnode = DFD.find((d) => d.id === dfdId)!;

  return (
    <>
      <div className="hero">
        <div className="eyebrow">Lakebridge migration · reconcile → resolve</div>
        <h1>From reconciliation mismatch to confident root cause — automatically.</h1>
        <p>
          <b>ReconResolve</b> is the stage <i>after</i> Lakebridge reconcile. It works for{" "}
          <b>any Lakebridge-supported source</b> migrating to Databricks — Snowflake, Oracle,
          Teradata, SQL Server, Synapse and more. A <b>deterministic</b> pass classifies every
          mismatch and confirms it with a live query; a <b>Genie Code / Foundation Model fallback</b>{" "}
          traces the leftovers back through the transpiled SQL &amp; lineage — still query-confirmed.
          Each finding lands as <b>migration-induced</b>, <b>genuine data</b>, <b>benign</b>, or{" "}
          <b>needs review</b> — with the fix, the owner, and a full audit trail.
        </p>
        <div className="cta">
          <button className="btn primary" onClick={() => nav("/trigger")}>⚡ Trigger a reconcile</button>
          <button className="btn" onClick={() => nav("/runs")}>📥 Browse recon runs</button>
          <button className="btn" onClick={() => nav("/audit")}>🧾 Audit trail</button>
        </div>
        <div className="src">
          {demo ? "Demo mode · bundled sample data" : <>Active source: <span className="mono">{catalog}.{config?.recon_schema}</span> · dialect {config?.dialect}</>}
        </div>
      </div>

      {/* Two ways in */}
      <div className="paths">
        <div className="path">
          <div className="num">1</div>
          <div>
            <div className="t">Start from tables</div>
            <div className="d">
              Point at a source &amp; target schema, pick table pairs — join keys are auto-detected —
              and ReconResolve reconciles them into a fresh <span className="mono">recon_id</span>, then runs RCA.
            </div>
          </div>
        </div>
        <div className="path blue">
          <div className="num">2</div>
          <div>
            <div className="t">Start from a recon_id</div>
            <div className="d">
              Already ran Lakebridge <span className="mono">reconcile</span>? Drop the{" "}
              <span className="mono">recon_id</span> in and jump straight to RCA — reconcile step skipped.
            </div>
          </div>
        </div>
      </div>

      {/* Interactive architecture: toggle between the process flow and the technical DFD */}
      <div className="panel arch">
        <div className="arch-head">
          <h3>
            {view === "detail"
              ? "Detailed technical flow — decisions, branches & the files that run them"
              : "Architecture — click any block to inspect it"}
          </h3>
          <div className="seg" role="tablist">
            <button className={view === "flow" ? "on" : ""} onClick={() => setView("flow")}>Process flow</button>
            <button className={view === "dfd" ? "on" : ""} onClick={() => setView("dfd")}>Technical DFD</button>
            <button className={view === "detail" ? "on" : ""} onClick={() => setView("detail")}>Detailed flow</button>
          </div>
        </div>

        {view === "flow" && (
          <>
            <div className="flow">
              {STAGES.map((s, i) => (
                <Fragment key={s.id}>
                  {i > 0 && <div className="flow-arrow">→</div>}
                  <div
                    className={`flow-stage click accent-${s.accent}${stageId === s.id ? " sel" : ""}`}
                    onClick={() => setStageId(s.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setStageId(s.id)}
                  >
                    <div className="head">
                      <span className="ic">{s.ic}</span>
                      <span className="lbl">{s.lbl}</span>
                      <span className="step">{s.step}</span>
                    </div>
                    <div className="flow-nodes">
                      {s.nodes.map((n) => (
                        <div key={n.n} className={`flow-node${n.mono ? " mono-n" : ""}${n.dashed ? " dashed" : ""}`}>
                          <div className="n">{n.n}</div>
                          {n.s && <div className="s">{n.s}</div>}
                        </div>
                      ))}
                    </div>
                  </div>
                </Fragment>
              ))}
            </div>

            {/* Live detail panel for the selected stage */}
            <div className={`flow-detail accent-${stage.accent}`}>
              <div className="fd-title"><span>{stage.ic}</span> {stage.lbl}</div>
              <div className="fd-does">{stage.detail.does}</div>
              <div className="fd-grid">
                <div>
                  <div className="fd-k">Inputs</div>
                  <ul>{stage.detail.inputs.map((x) => <li key={x}>{x}</li>)}</ul>
                </div>
                <div>
                  <div className="fd-k">Outputs</div>
                  <ul>{stage.detail.outputs.map((x) => <li key={x}>{x}</li>)}</ul>
                </div>
                <div>
                  <div className="fd-k">Runs on</div>
                  <div className="fd-runs">{stage.detail.runs}</div>
                  {stage.detail.link && (
                    <button className="btn" style={{ marginTop: 10 }} onClick={() => nav(stage.detail.link!.to)}>
                      {stage.detail.link.label}
                    </button>
                  )}
                </div>
              </div>
            </div>

            <div className="flow-loop">
              <span style={{ fontSize: 18 }}>↩︎</span>
              <span>
                <b>Feedback loop:</b> migration-induced findings tell the engineer exactly what to fix in
                the transpiled SQL / mapping — then re-run the reconcile and RCA to confirm the diff is gone.
              </span>
            </div>
          </>
        )}

        {view === "dfd" && (
          <>
            <div className="dfd">
              <div className="dfd-col">
                <div className="dfd-col-h">External entities</div>
                {DFD.filter((d) => d.kind === "entity").map((d) => (
                  <DfdBlock key={d.id} d={d} sel={dfdId === d.id} onSel={setDfdId} />
                ))}
              </div>
              <div className="dfd-col wide">
                <div className="dfd-col-h">Processes (data transforms)</div>
                {DFD.filter((d) => d.kind === "process").map((d, i, arr) => (
                  <Fragment key={d.id}>
                    <DfdBlock d={d} sel={dfdId === d.id} onSel={setDfdId} />
                    {i < arr.length - 1 && <div className="dfd-down">▼</div>}
                  </Fragment>
                ))}
              </div>
              <div className="dfd-col">
                <div className="dfd-col-h">Data stores</div>
                {DFD.filter((d) => d.kind === "store").map((d) => (
                  <DfdBlock key={d.id} d={d} sel={dfdId === d.id} onSel={setDfdId} />
                ))}
              </div>
            </div>

            {/* Selected DFD node detail */}
            <div className={`flow-detail dfd-detail k-${dnode.kind}`}>
              <div className="fd-title">
                <span className="dfd-kind">{KIND_LABEL[dnode.kind]}</span> {dnode.label}
              </div>
              <div className="fd-does">{dnode.detail}</div>
              <div className="fd-grid two">
                <div>
                  <div className="fd-k">Data in</div>
                  <ul>{(dnode.inflows && dnode.inflows.length ? dnode.inflows : ["—"]).map((x) => <li key={x}>{x}</li>)}</ul>
                </div>
                <div>
                  <div className="fd-k">Data out</div>
                  <ul>{(dnode.outflows && dnode.outflows.length ? dnode.outflows : ["—"]).map((x) => <li key={x}>{x}</li>)}</ul>
                </div>
              </div>
            </div>

            <div className="dfd-legend">
              <span><i className="lg ent" /> External entity</span>
              <span><i className="lg proc" /> Process</span>
              <span><i className="lg store" /> Data store</span>
              <span className="muted">Numbers show data-flow order (1.0 → 7.0).</span>
            </div>
          </>
        )}

        {view === "detail" && (
          <>
            <div className="dflow-surfaces">
              The pipeline below is the <b>Genie Code skill</b>{" "}
              (<span className="ftag mono">skill/rca-recon</span>). You can run it three ways, all
              executing the same skill code: <b>interactively</b> in Genie Code, from the{" "}
              <b>CLI/jobs</b> (<span className="ftag mono">rca_engine/cli.py</span>), or from{" "}
              <b>this app</b> — whose backend (<span className="ftag mono">app/server/skill_job.py</span>)
              submits the skill's <span className="ftag mono">job_entry</span> notebook as a{" "}
              <b>serverless Databricks Job</b>, then reads the bundle back. Genie Code is also the{" "}
              <b>Tier-2 actor at step 8</b>.
            </div>
            <div className="dflow">
              {DETAIL_STEPS.map((s, i) => (
                <Fragment key={s.id}>
                  {i > 0 && <div className="dflow-conn">↓</div>}
                  <DetailStep s={s} />
                </Fragment>
              ))}
            </div>
            <div className="dfd-legend">
              <span><i className="lg term" /> Start / end</span>
              <span><i className="lg proc" /> Process</span>
              <span><i className="lg dec" /> Decision (branches)</span>
              <span><i className="lg store" /> Data store</span>
              <span className="muted">Each block tags the repo file(s) that implement it.</span>
            </div>
          </>
        )}
      </div>

      {/* Under the hood */}
      <div className="grid uh">
        <div className="card">
          <div className="t">🧪 Deterministic first</div>
          <div className="d">
            Typed probes explain each mismatch (scale loss, timezone shift, null/boolean encoding,
            string normalization, volume gaps) and every verdict is backed by a query that actually ran.
          </div>
        </div>
        <div className="card">
          <div className="t">🧠 LLM fallback, still proven</div>
          <div className="d">
            Only the residual findings go to the Genie Code / Foundation Model tier, which traces the
            cause through the transpiled SQL + UC lineage and must <b>confirm it with a query</b> before
            the verdict sticks — coverage on the long tail without guessing.
          </div>
        </div>
        <div className="card">
          <div className="t">🧾 Audit &amp; lineage</div>
          <div className="d">
            Each reconcile and RCA step logs one row (who, when, scope, outcome, notebook) grouped by a
            run id — shared by the app, the skill, and the CLI.
          </div>
        </div>
      </div>
    </>
  );
}

function DfdBlock({ d, sel, onSel }: { d: DfdNode; sel: boolean; onSel: (id: string) => void }) {
  return (
    <div
      className={`dfd-node ${d.kind}${sel ? " sel" : ""}`}
      onClick={() => onSel(d.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSel(d.id)}
    >
      <div className="dn">{d.label}</div>
      {d.sub && <div className="ds">{d.sub}</div>}
    </div>
  );
}

function DetailStep({ s }: { s: FlowStep }) {
  return (
    <div className={`dstep ${s.kind}`}>
      <div className="dstep-block">
        <div className="dstep-head">
          {s.kind === "decision" && <span className="dstep-ic dec">◆</span>}
          {s.kind === "store" && <span className="dstep-ic store">🗄️</span>}
          {s.kind === "terminal" && <span className="dstep-ic term">{s.ic}</span>}
          {s.n && <span className="dstep-n">{s.n}</span>}
          <span className="dstep-lbl">{s.label}</span>
        </div>
        {s.desc && <div className="dstep-desc">{s.desc}</div>}
        {s.files && s.files.length > 0 && (
          <div className="dstep-files">
            {s.files.map((f) => <span key={f} className="ftag mono">{f}</span>)}
          </div>
        )}
      </div>
      {s.branches && s.branches.length > 0 && (
        <div className="dstep-branches">
          {s.branches.map((b) => (
            <div key={b.cond} className={`branch tone-${b.tone}`}>
              <span className="cond">{b.cond}</span>
              <span className="arr">→</span>
              <span className="to">{b.to}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
