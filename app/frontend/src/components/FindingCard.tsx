import type { FindingView } from "../types";
import { SeverityBadge, VerdictBadge } from "./Badges";
import { LineageFlow, hasLineageFlow } from "./LineageFlow";

// Friendly names + icons for each evidence type (mirrors the RCA notebook's sections).
const EV_META: Record<string, { icon: string; name: string }> = {
  code: { icon: "🔧", name: "Transformation logic" },
  code_generated: { icon: "🔧", name: "Transformation logic" },
  drilldown: { icon: "✔", name: "Confirming query" },
  llm_drilldown: { icon: "🧠", name: "Agentic reconstruction (query-confirmed)" },
  lineage: { icon: "🔗", name: "UC lineage" },
  drift: { icon: "📊", name: "Distribution drift" },
  probe: { icon: "🔬", name: "Probe" },
  row_counts: { icon: "🔢", name: "Row counts" },
  fix: { icon: "🛠", name: "Suggested fix" },
};

/** Split a code-evidence detail into the transform text and the "[in <path> … line N]" location. */
function splitCode(detail: string): { text: string; loc: string | null } {
  const m = detail.match(/\[in\s+([^\]]+)\]/i);
  return m ? { text: detail.replace(m[0], "").trim(), loc: m[1].trim() } : { text: detail, loc: null };
}

export function FindingCard({ f, defaultOpen }: { f: FindingView; defaultOpen?: boolean }) {
  // When the visual lineage flow renders, it already shows the source logic, the migrated
  // transform (+ script location) and the lineage — so drop those from the text evidence to
  // avoid duplicates. What remains below is the confirming query, drift, row counts and fix.
  const flow = hasLineageFlow(f);
  const DEDUP = new Set(["source_code", "code", "code_generated", "lineage"]);
  const evidence = flow ? f.evidence.filter((e) => !DEDUP.has(e.label)) : f.evidence;
  return (
    <details className="finding" open={defaultOpen ?? f.severity === "High"}>
      <summary>
        <SeverityBadge severity={f.severity} score={f.severity_score} />
        <span className="loc mono">{f.location}</span>
        <VerdictBadge verdict={f.verdict} />
        <span className="spread" />
        {f.confirmed && <span className="badge v-benign">✓ confirmed</span>}
        <span className="pill">{f.category || f.recon_type}</span>
        <span className="pill">conf {(f.confidence * 100).toFixed(0)}%</span>
      </summary>
      <div className="body">
        <LineageFlow f={f} />
        <div className="kv">
          <span className="k">Root cause</span><span>{f.rationale}</span>
          <span className="k">Solution / fix</span><span>{f.remediation || "—"}</span>
          <span className="k">Owner</span><span>{f.owner || "—"}</span>
          {f.total_count > 0 && f.mismatch_count > 0 && (
            <>
              <span className="k">Rows affected</span>
              <span className="mono">
                {f.mismatch_count.toLocaleString()} of {f.total_count.toLocaleString()}
                {" "}({(100 * f.mismatch_count / f.total_count).toFixed(
                  f.mismatch_count / f.total_count < 0.01 ? 3 : 2)}% of rows)
              </span>
            </>
          )}
        </div>

        {evidence.length > 0 && (
          <div>
            <div className="k muted" style={{ marginBottom: 6 }}>Evidence</div>
            {evidence.map((e, i) => {
              const meta = EV_META[e.label] || { icon: "•", name: e.label };
              const isCode = e.label === "code" || e.label === "code_generated";
              const c = isCode ? splitCode(e.detail) : null;
              return (
                <div className="evidence" key={i}>
                  <div className="lbl">{meta.icon} {meta.name}</div>
                  {c ? (
                    <>
                      <div className="mono" style={{ fontSize: 12.5 }}>{c.text}</div>
                      {c.loc && (
                        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                          📄 Script location: <span className="mono">{c.loc}</span>
                        </div>
                      )}
                    </>
                  ) : (
                    <div>{e.detail}</div>
                  )}
                  {e.query && <pre className="q">{e.query}</pre>}
                </div>
              );
            })}
          </div>
        )}

        {f.samples.length > 0 && (
          <div>
            <div className="k muted" style={{ marginBottom: 6 }}>Sample differences</div>
            <table className="samples">
              <thead>
                <tr><th>Keys</th><th>Source</th><th>Target</th></tr>
              </thead>
              <tbody>
                {f.samples.map((s, i) => (
                  <tr key={i}>
                    <td className="mono muted">{JSON.stringify(s.keys)}</td>
                    <td className="mono">{String(s.source)}</td>
                    <td className="mono">{String(s.target)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </details>
  );
}
