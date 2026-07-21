import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { FindingView, RunView } from "../types";
import { SeverityBadge, VerdictBadge } from "../components/Badges";

function FindingCard({ f }: { f: FindingView }) {
  return (
    <details className="finding" open={f.severity === "High"}>
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

export function TablePage() {
  const { reconId = "", table = "" } = useParams();
  const [view, setView] = useState<RunView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.run(reconId).then(setView).catch((e) => setError(String(e.message || e)));
  }, [reconId]);

  if (error) return <div className="panel" style={{ borderColor: "var(--lava)" }}>⚠️ {error}</div>;
  if (!view) return <div className="center-msg"><div className="spinner" /></div>;

  const meta = view.tables.find((t) => t.name === table);
  const findings = view.findings.filter((f) => f.table === table);

  return (
    <>
      <div className="crumbs">
        <Link to="/">Recon runs</Link> /{" "}
        <Link to={`/runs/${encodeURIComponent(view.recon_id)}`}>{view.recon_id}</Link> /{" "}
        <span className="mono">{table}</span>
      </div>
      <div className="topbar">
        <div>
          <div className="title mono">{table}</div>
          <div className="subtitle">
            {meta ? (
              <>
                {meta.source_count.toLocaleString()} → {meta.target_count.toLocaleString()} rows ·{" "}
                row match {meta.row_match_pct.toFixed(2)}% · {findings.length} finding(s)
              </>
            ) : (
              `${findings.length} finding(s)`
            )}
          </div>
        </div>
      </div>

      {findings.length === 0 ? (
        <div className="panel center-msg">✅ No findings for this table — clean.</div>
      ) : (
        findings.map((f) => <FindingCard key={f.location} f={f} />)
      )}
    </>
  );
}
