import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { RunView } from "../types";
import { MatchBar, SeverityBadge, VerdictBadge } from "../components/Badges";
import { VerdictDonut } from "../components/Charts";

export function OverviewPage() {
  const { reconId = "" } = useParams();
  const [view, setView] = useState<RunView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setView(null);
    setError(null);
    api.run(reconId).then(setView).catch((e) => setError(String(e.message || e)));
  }, [reconId]);

  if (error) return <div className="panel" style={{ borderColor: "var(--lava)" }}>⚠️ {error}</div>;
  if (!view) return <div className="center-msg"><div className="spinner" /></div>;

  const c = view.verdict_counts;
  return (
    <>
      <div className="crumbs">
        <Link to="/">Recon runs</Link> / <span className="mono">{view.recon_id}</span>
      </div>
      <div className="topbar">
        <div>
          <div className="title">Run dashboard</div>
          <div className="subtitle">
            {view.findings_total} findings across {view.table_pairs} table pairs · dialect{" "}
            <code>{view.dialect}</code>
          </div>
        </div>
        <a className="btn" href={api.summaryUrl(view.recon_id)} target="_blank" rel="noreferrer">
          ⬇ SUMMARY.md
        </a>
      </div>

      {/* KPI tiles */}
      <div className="grid cards">
        <div className="card">
          <div className="k">Overall row match</div>
          <div className="v">{view.overall_row_match_pct.toFixed(1)}<small>%</small></div>
        </div>
        <div className="card">
          <div className="k">🔧 Migration-induced</div>
          <div className="v" style={{ color: "var(--lava-2)" }}>{c.migration_induced || 0}</div>
        </div>
        <div className="card">
          <div className="k">📊 Genuine data</div>
          <div className="v" style={{ color: "var(--blue)" }}>{c.genuine_data || 0}</div>
        </div>
        <div className="card">
          <div className="k">🔍 Needs review</div>
          <div className="v" style={{ color: "var(--amber)" }}>{c.needs_review || 0}</div>
        </div>
      </div>

      <div className="row section">
        <div className="panel" style={{ flex: "0 0 360px" }}>
          <h3>Verdict distribution</h3>
          <VerdictDonut view={view} />
        </div>
        <div className="panel spread">
          <h3>🔺 Top priorities</h3>
          <table>
            <thead>
              <tr><th>Severity</th><th>Location</th><th>Verdict</th><th>Fix / next step</th></tr>
            </thead>
            <tbody>
              {view.top_priorities.map((f) => (
                <tr key={f.location}>
                  <td><SeverityBadge severity={f.severity} score={f.severity_score} /></td>
                  <td className="mono">
                    <Link to={`/runs/${encodeURIComponent(view.recon_id)}/${encodeURIComponent(f.table)}`}>
                      {f.location}
                    </Link>
                  </td>
                  <td><VerdictBadge verdict={f.verdict} /></td>
                  <td className="muted">{f.remediation || f.rationale}</td>
                </tr>
              ))}
              {view.top_priorities.length === 0 && (
                <tr><td colSpan={4} className="muted">No actionable findings — clean run. ✅</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel section">
        <h3>Tables (worst first)</h3>
        <table>
          <thead>
            <tr>
              <th>Table</th>
              <th>Severity</th>
              <th className="num">Src rows</th>
              <th className="num">Tgt rows</th>
              <th className="num">Missing</th>
              <th className="num">Extra</th>
              <th className="num">Mismatch</th>
              <th style={{ width: 180 }}>Row match</th>
              <th className="num">Findings</th>
            </tr>
          </thead>
          <tbody>
            {view.tables.map((t) => (
              <tr key={t.name} className="clickable">
                <td className="mono">
                  <Link to={`/runs/${encodeURIComponent(view.recon_id)}/${encodeURIComponent(t.name)}`}>
                    {t.name}
                  </Link>
                </td>
                <td>{t.max_severity ? <SeverityBadge severity={t.max_severity} /> : <span className="badge v-benign">clean</span>}</td>
                <td className="num">{t.source_count.toLocaleString()}</td>
                <td className="num">{t.target_count.toLocaleString()}</td>
                <td className="num">{t.missing_in_target || "·"}</td>
                <td className="num">{t.missing_in_source || "·"}</td>
                <td className="num">{t.absolute_mismatch || "·"}</td>
                <td><MatchBar pct={t.row_match_pct} /></td>
                <td className="num">{t.findings_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
