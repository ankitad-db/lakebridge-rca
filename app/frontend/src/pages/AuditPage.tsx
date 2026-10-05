import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDateTime } from "../format";
import type { AppConfig, AuditRow } from "../types";

const OP_ICON: Record<string, string> = { reconcile: "🔁", rca: "🔬", analyze_table: "🔬" };

/** Friendly actor name — a service-principal GUID reads as the app; an email trims to its user. */
function fmtActor(by: string | null | undefined): string {
  if (!by) return "—";
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(by)) return "rca-genie (app)";
  return by.includes("@") ? by.split("@")[0] : by;
}

function fmtDur(ms: number): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export function AuditPage({ config }: { config: AppConfig | null }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [table, setTable] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();

  function load() {
    setRows(null);
    setError(null);
    api
      .audit(100)
      .then((r) => {
        setRows(r.rows);
        setTable(r.audit_table);
      })
      .catch((e) => setError(String(e.message || e)));
  }

  useEffect(load, []);

  return (
    <>
      <div className="topbar">
        <div>
          <div className="title">Audit trail</div>
          <div className="subtitle">
            Every reconcile &amp; RCA step — what ran, when, by whom, and the outcome. Append-only.
          </div>
        </div>
        <div className="row" style={{ gap: 10, alignItems: "center" }}>
          {table ? (
            <span className="mono muted" style={{ fontSize: 12 }}>{table}</span>
          ) : (
            config?.demo_mode && <span className="demo-pill">DEMO · no audit table</span>
          )}
          <button className="btn" onClick={load}>↻ Refresh</button>
        </div>
      </div>

      {error && <div className="panel" style={{ borderColor: "var(--lava)" }}>⚠️ {error}</div>}
      {!rows && !error && (
        <div className="center-msg"><div className="spinner" /></div>
      )}
      {rows && rows.length === 0 && (
        <div className="panel center-msg">
          No audit rows yet. Trigger a reconcile or run an RCA and the steps will be recorded here.
          {!table && (
            <div className="muted" style={{ marginTop: 8, fontSize: 13 }}>
              Auditing is disabled (no <code>RCA_AUDIT_TABLE</code> / catalog configured).
            </div>
          )}
        </div>
      )}
      {rows && rows.length > 0 && (
        <div className="panel" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Step</th>
                <th>Status</th>
                <th>recon_id</th>
                <th>Source → Target</th>
                <th className="num">Pairs</th>
                <th className="num">Diffs</th>
                <th className="num">Findings</th>
                <th className="num">Duration</th>
                <th>By</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.run_id}-${i}`}>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>{fmtDateTime(r.started_ts)}</td>
                  <td>
                    <span style={{ fontWeight: 600 }}>
                      {OP_ICON[r.operation] || "•"} {r.operation}
                    </span>
                    {r.message && (
                      <div className="muted" style={{ fontSize: 12, maxWidth: 320 }}>{r.message}</div>
                    )}
                  </td>
                  <td>
                    {r.status === "ok" ? (
                      <span className="badge v-benign">✅ ok</span>
                    ) : (
                      <span className="badge v-migration">⚠️ error</span>
                    )}
                  </td>
                  <td className="mono muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                    {r.recon_id ? (
                      <a
                        onClick={() => nav(`/runs/${encodeURIComponent(r.recon_id!)}`)}
                        title={r.recon_id}
                        style={{ cursor: "pointer", color: "var(--accent, #ff5f46)" }}
                      >
                        {r.recon_id}
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="muted" style={{ fontSize: 12 }}>
                    {r.source_schema && r.target_schema ? `${r.source_schema} → ${r.target_schema}` : "—"}
                  </td>
                  <td className="num">
                    {r.operation === "reconcile"
                      ? `${r.pairs_ok}/${r.table_pairs}`
                      : r.table_pairs || "—"}
                  </td>
                  <td className="num">{r.tables_with_diffs || (r.operation === "rca" ? 0 : "—")}</td>
                  <td className="num">{r.operation === "rca" ? r.findings_total : "—"}</td>
                  <td className="num muted">{fmtDur(r.duration_ms)}</td>
                  <td className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                    <span title={r.run_by || ""}>{fmtActor(r.run_by)}</span>
                    {r.tool && <span className="pill" style={{ marginLeft: 6 }}>{r.tool}</span>}
                  </td>
                  <td className="num" onClick={(e) => e.stopPropagation()}>
                    {r.notebook_path && config?.workspace_host && (
                      <a
                        className="btn"
                        href={`${config.workspace_host}/#workspace${r.notebook_path}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        📓 Notebook
                      </a>
                    )}
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
