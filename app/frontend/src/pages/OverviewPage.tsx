import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { JobStatus, RunView } from "../types";
import { MatchBar, SeverityBadge, VerdictBadge } from "../components/Badges";
import { VerdictDonut } from "../components/Charts";
import { ModeToggle } from "../components/ModeToggle";

export function OverviewPage() {
  const { reconId = "" } = useParams();
  const [view, setView] = useState<RunView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [nbDir, setNbDir] = useState<string>("");
  const poll = useRef<number | null>(null);

  const loadView = useCallback(() => {
    setLoading(true);
    return api
      .run(reconId)
      .then((v) => {
        setView(v);
        setError(null);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [reconId]);

  useEffect(() => {
    setView(null);
    setError(null);
    loadView();
    // Prefill the notebook target from the app config (env default).
    api.config().then((c) => setNbDir((prev) => prev || c.notebook_dir || "")).catch(() => undefined);
    // Surface an already-running / previously-finished full-run job.
    api.job(reconId).then((j) => {
      if (j.state !== "idle") setJob(j);
      if (j.state === "running") startPolling();
    }).catch(() => undefined);
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reconId]);

  function startPolling() {
    if (poll.current) window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      try {
        const j = await api.job(reconId);
        setJob(j);
        if (j.state === "done" || j.state === "error") {
          if (poll.current) window.clearInterval(poll.current);
          poll.current = null;
          if (j.state === "done") loadView();
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
  }

  async function runFull() {
    try {
      const j = await api.analyzeAll(reconId, true, nbDir.trim() || undefined);
      setJob(j);
      if (j.state === "running") startPolling();
      else if (j.state === "done") loadView();
    } catch (e) {
      setJob({ state: "error", message: String((e as Error).message || e) });
    }
  }

  const running = job?.state === "running";

  const runFullBtn = (
    <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
      <input
        className="mono"
        title="Workspace folder to publish notebooks into (a rca_<recon_id> subfolder is created)"
        placeholder="notebook target folder…"
        value={nbDir}
        onChange={(e) => setNbDir(e.target.value)}
        disabled={running}
        style={{
          width: 340, padding: "8px 10px", borderRadius: 8, fontSize: 12,
          border: "1px solid var(--border-2)", background: "var(--panel-2)", color: "var(--text)",
        }}
      />
      <ModeToggle compact />
      <button className="btn primary" onClick={runFull} disabled={running}>
        {running ? "Running full RCA…" : "▶ Run full RCA & generate notebook"}
      </button>
    </div>
  );

  const jobBanner = job && job.state !== "idle" && (
    <div
      className="panel section"
      style={{
        borderColor:
          job.state === "error" ? "var(--lava)" : job.state === "done" ? "var(--green, #3fb950)" : "var(--amber)",
      }}
    >
      {job.state === "running" && (
        <div className="row" style={{ alignItems: "center", gap: 10 }}>
          <div className="spinner" /> <span>{job.message || "Analyzing all tables…"}</span>
        </div>
      )}
      {job.state === "done" && (
        <div>
          ✅ {job.message} {job.tables != null && <span className="muted">· {job.tables} tables · {job.findings} findings</span>}
          {job.notebook_url ? (
            <div style={{ marginTop: 8 }}>
              📓 Notebook published to the workspace:{" "}
              <a className="btn" href={job.notebook_url} target="_blank" rel="noreferrer">
                Open in workspace ↗
              </a>
              <div className="mono muted" style={{ fontSize: 12, marginTop: 6 }}>{job.notebook_path}</div>
            </div>
          ) : (
            <div className="muted" style={{ marginTop: 6 }}>{job.notebook_path || "Notebook publish skipped."}</div>
          )}
        </div>
      )}
      {job.state === "error" && <div style={{ color: "var(--lava-2)" }}>⚠️ {job.message}</div>}
    </div>
  );

  // Empty / not-yet-analyzed state: offer the full-run action instead of a dead error.
  if (!loading && !view) {
    return (
      <>
        <div className="crumbs">
          <Link to="/runs">Recon runs</Link> / <span className="mono">{reconId}</span>
        </div>
        <div className="topbar">
          <div>
            <div className="title">Run dashboard</div>
            <div className="subtitle">This run hasn’t been analyzed yet — run the full RCA to populate the dashboard and generate notebooks.</div>
          </div>
          {runFullBtn}
        </div>
        {jobBanner}
        {!job && (
          <div className="panel center-msg">
            <div>
              <p className="muted" style={{ marginBottom: 12 }}>
                Or analyze one table at a time on the{" "}
                <Link to={`/analyze/${encodeURIComponent(reconId)}`}>Analyze page</Link>.
              </p>
              {runFullBtn}
            </div>
          </div>
        )}
      </>
    );
  }

  if (loading && !view) return <div className="center-msg"><div className="spinner" /></div>;
  if (!view) return <div className="panel" style={{ borderColor: "var(--lava)" }}>⚠️ {error}</div>;

  const c = view.verdict_counts;
  return (
    <>
      <div className="crumbs">
        <Link to="/runs">Recon runs</Link> / <span className="mono">{view.recon_id}</span>
      </div>
      <div className="topbar">
        <div>
          <div className="title">Run dashboard</div>
          <div className="subtitle">
            {view.findings_total} findings across {view.table_pairs} table pairs · dialect{" "}
            <code>{view.dialect}</code>
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {runFullBtn}
          <a className="btn" href={api.summaryUrl(view.recon_id)} target="_blank" rel="noreferrer">
            ⬇ SUMMARY.md
          </a>
        </div>
      </div>

      {jobBanner}

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
