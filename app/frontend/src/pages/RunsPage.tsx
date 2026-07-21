import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { AppConfig, ReconRun } from "../types";

export function RunsPage({ config }: { config: AppConfig | null }) {
  const [runs, setRuns] = useState<ReconRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();

  useEffect(() => {
    api.runs().then(setRuns).catch((e) => setError(String(e.message || e)));
  }, []);

  return (
    <>
      <div className="topbar">
        <div>
          <div className="title">Reconciliation runs</div>
          <div className="subtitle">
            Pick a Lakebridge reconcile run to analyze. Root cause, verdict, and fix per finding.
          </div>
        </div>
        {config?.demo_mode && <span className="demo-pill">DEMO · bundled sample data</span>}
      </div>

      {error && <div className="panel" style={{ borderColor: "var(--lava)" }}>⚠️ {error}</div>}
      {!runs && !error && (
        <div className="center-msg"><div className="spinner" /></div>
      )}
      {runs && runs.length === 0 && (
        <div className="panel center-msg">
          No reconcile runs found. Run <code>databricks labs lakebridge reconcile</code> first.
        </div>
      )}
      {runs && runs.length > 0 && (
        <div className="panel">
          <table>
            <thead>
              <tr>
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
                  onClick={() => nav(`/runs/${encodeURIComponent(r.recon_id)}`)}
                >
                  <td className="mono">{r.recon_id}</td>
                  <td className="muted">{r.started || "—"}</td>
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
                  <td className="num">
                    <span className="btn">Analyze →</span>
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
