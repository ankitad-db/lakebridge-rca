import type { FindingView } from "../types";
import { SeverityBadge, VerdictBadge } from "./Badges";

export function FindingCard({ f, defaultOpen }: { f: FindingView; defaultOpen?: boolean }) {
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
        <div className="kv">
          <span className="k">Root cause</span><span>{f.rationale}</span>
          <span className="k">Remediation</span><span>{f.remediation || "—"}</span>
          <span className="k">Owner</span><span>{f.owner || "—"}</span>
          {f.match_pct !== null && (
            <>
              <span className="k">Column match</span>
              <span className="mono">
                {f.match_pct.toFixed(2)}% ({f.mismatch_count.toLocaleString()} /{" "}
                {f.total_count.toLocaleString()} mismatched)
              </span>
            </>
          )}
        </div>

        {f.evidence.length > 0 && (
          <div>
            <div className="k muted" style={{ marginBottom: 6 }}>Evidence</div>
            {f.evidence.map((e, i) => (
              <div className="evidence" key={i}>
                <div className="lbl">{e.label}</div>
                <div>{e.detail}</div>
                {e.query && <pre className="q">{e.query}</pre>}
              </div>
            ))}
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
