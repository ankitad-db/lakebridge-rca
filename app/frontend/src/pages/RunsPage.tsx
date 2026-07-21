import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { AppConfig, ReconRun } from "../types";

export function RunsPage({ config }: { config: AppConfig | null }) {
  const [runs, setRuns] = useState<ReconRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reconInput, setReconInput] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    api.runs().then(setRuns).catch((e) => setError(String(e.message || e)));
  }, []);

  function go(id: string) {
    const v = id.trim();
    if (v) nav(`/analyze/${encodeURIComponent(v)}`);
  }

  return (
    <>
      <div className="topbar">
        <div>
          <div className="title">Reconciliation runs</div>
          <div className="subtitle">
            Pick a Lakebridge reconcile run to analyze. Root cause, verdict, and fix per finding.
          </div>
        </div>
        <div className="row" style={{ gap: 10, alignItems: "center" }}>
          {config?.demo_mode && <span className="demo-pill">DEMO · bundled sample data</span>}
          <button className="btn primary" onClick={() => nav("/trigger")}>⚡ Trigger new recon</button>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3>Run RCA on a recon_id</h3>
        <div className="row" style={{ alignItems: "center", gap: 10 }}>
          <input
            className="mono"
            placeholder="paste a recon_id…"
            value={reconInput}
            onChange={(e) => setReconInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go(reconInput)}
            style={{
              flex: 1, minWidth: 260, padding: "9px 12px", borderRadius: 9,
              border: "1px solid var(--border-2)", background: "var(--panel-2)", color: "var(--text)",
            }}
          />
          <button className="btn primary" onClick={() => go(reconInput)}>▶ Analyze table-by-table</button>
        </div>
      </div>

      {error && <div className="panel" style={{ borderColor: "var(--lava)" }}>⚠️ {error}</div>}
      {!runs && !error && (
        <div className="center-msg"><div className="spinner" /></div>
      )}
      {runs && runs.length === 0 && (
        <div className="panel center-msg">
          No reconcile runs found. Run <code>databricks labs lakebridge reconcile</code>, or{" "}
          <button className="btn primary" style={{ marginLeft: 8 }} onClick={() => nav("/trigger")}>
            ⚡ Trigger one here
          </button>
        </div>
      )}
      {runs && runs.length > 0 && (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>recon_id</th>
                <th>Started</th>
                <th className="num">Table pairs</th>
                <th className="num">With diffs</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.recon_id}
                  className="clickable"
                  onClick={() => nav(`/analyze/${encodeURIComponent(r.recon_id)}`)}
                >
                  <td>
                    <div style={{ fontWeight: 600 }}>{r.title || "Reconcile run"}</div>
                    {r.source && <div className="muted" style={{ fontSize: 12 }}>{r.source}</div>}
                  </td>
                  <td className="mono muted" style={{ fontSize: 12 }}>{r.recon_id}</td>
                  <td className="muted">{r.started ? new Date(r.started).toLocaleString() : "—"}</td>
                  <td className="num">{r.table_pairs}</td>
                  <td className="num">{r.tables_with_diffs < 0 ? "?" : r.tables_with_diffs}</td>
                  <td>
                    {r.clean ? (
                      <span className="badge v-benign">✅ clean</span>
                    ) : (
                      <span className="badge v-migration">⚠️ has diffs</span>
                    )}
                    {r.has_bundle === false && <span className="pill" style={{ marginLeft: 8 }}>no bundle</span>}
                  </td>
                  <td className="num" onClick={(e) => e.stopPropagation()}>
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                      <button className="btn primary" onClick={() => nav(`/analyze/${encodeURIComponent(r.recon_id)}`)}>
                        ▶ Run RCA
                      </button>
                      <button className="btn" onClick={() => nav(`/runs/${encodeURIComponent(r.recon_id)}`)}>
                        Dashboard
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
