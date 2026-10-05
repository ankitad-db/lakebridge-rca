import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDate } from "../format";
import type { AppConfig, Portfolio } from "../types";

const VERDICT_COLOR: Record<string, string> = {
  migration_induced: "var(--lava)",
  genuine_data: "var(--blue)",
  benign: "var(--green)",
  needs_review: "var(--amber)",
};
const VERDICT_ORDER = ["migration_induced", "genuine_data", "benign", "needs_review"];

export function PortfolioPage({ config }: { config: AppConfig | null }) {
  const [p, setP] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();

  useEffect(() => {
    setP(null);
    setError(null);
    api.portfolio().then(setP).catch((e) => setError(String(e.message || e)));
  }, []);

  if (error) return <div className="topbar"><div><div className="title">Migration Health</div><div className="subtitle" style={{ color: "var(--lava-2)" }}>{error}</div></div></div>;
  if (!p) return <div className="topbar"><div><div className="title">Migration Health</div><div className="subtitle">Loading migration-wide roll-up…</div></div></div>;

  const totalVerdicts = VERDICT_ORDER.reduce((n, v) => n + (p.verdict_counts[v] || 0), 0);
  const matchPct = p.table_pairs ? Math.round((p.tables_clean / p.table_pairs) * 100) : 0;
  const maxCause = p.top_causes.reduce((m, c) => Math.max(m, c.count), 1);

  return (
    <>
      <div className="topbar">
        <div>
          <div className="title">Migration Health</div>
          <div className="subtitle">
            Migration-wide roll-up across <b>{p.recons}</b> recon{p.recons === 1 ? "" : "s"}
            {p.with_rca < p.recons && <> · {p.with_rca} with RCA detail</>}
            {config?.demo_mode && <> · demo data</>}
          </div>
        </div>
      </div>

      {/* Headline stats */}
      <div className="grid cards" style={{ marginBottom: 18 }}>
        <div className="card"><div className="k">Recon runs</div><div className="v">{p.recons}</div></div>
        <div className="card"><div className="k">Tables reconciled</div><div className="v">{p.table_pairs}</div></div>
        <div className="card"><div className="k">Tables matching</div><div className="v">{p.tables_clean}<small> / {p.table_pairs} · {matchPct}%</small></div></div>
        <div className="card"><div className="k">Findings</div><div className="v">{p.findings_total}</div></div>
        <div className="card"><div className="k">Actionable</div><div className="v" style={{ color: "var(--lava-2)" }}>{p.actionable}<small> migration + data</small></div></div>
      </div>

      <div className="row">
        {/* Verdict mix across the whole migration */}
        <div className="panel spread">
          <h3>Verdict mix — all recons</h3>
          {totalVerdicts === 0 ? (
            <div className="subtitle">No concluded findings yet. Run RCA on a recon to populate this.</div>
          ) : (
            <>
              <div style={{ display: "flex", height: 14, borderRadius: 7, overflow: "hidden", margin: "12px 0 14px", border: "1px solid var(--border)" }}>
                {VERDICT_ORDER.map((v) => {
                  const n = p.verdict_counts[v] || 0;
                  if (!n) return null;
                  return <div key={v} title={`${p.verdict_meta[v]?.label}: ${n}`} style={{ width: `${(n / totalVerdicts) * 100}%`, background: VERDICT_COLOR[v] }} />;
                })}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 18px" }}>
                {VERDICT_ORDER.map((v) => {
                  const n = p.verdict_counts[v] || 0;
                  const meta = p.verdict_meta[v];
                  return (
                    <div key={v} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13 }}>
                      <span style={{ width: 9, height: 9, borderRadius: "50%", background: VERDICT_COLOR[v] }} />
                      <span>{meta?.icon} {meta?.label}</span>
                      <b style={{ fontVariantNumeric: "tabular-nums" }}>{n}</b>
                      <span style={{ color: "var(--muted-2)" }}>{totalVerdicts ? Math.round((n / totalVerdicts) * 100) : 0}%</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* Top recurring root causes */}
        <div className="panel spread">
          <h3>Top recurring root causes</h3>
          {p.top_causes.length === 0 ? (
            <div className="subtitle">No classified causes yet.</div>
          ) : (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 9 }}>
              {p.top_causes.map((c) => (
                <div key={c.category} style={{ display: "grid", gridTemplateColumns: "150px 1fr 32px", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 13 }}>{c.label}</span>
                  <span style={{ height: 8, borderRadius: 4, background: "linear-gradient(90deg, var(--lava), var(--lava-2))", width: `${Math.max(6, (c.count / maxCause) * 100)}%` }} />
                  <b style={{ fontSize: 13, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{c.count}</b>
                </div>
              ))}
            </div>
          )}
          <div className="subtitle" style={{ marginTop: 12, fontSize: 12 }}>
            The same cause across many tables → one fix clears the most diffs.
          </div>
        </div>
      </div>

      {/* Per-recon breakdown — health signals only (findings + verdict mix). Raw pair/diff
          counts live on the Runs page (act) and Audit trail (history); this table is the
          health rollup + drill-in, so it doesn't repeat them. */}
      <div className="panel section">
        <h3>By recon <span style={{ color: "var(--muted-2)", fontWeight: 400, fontSize: 12 }}>· click a row to open its dashboard</span></h3>
        <table>
          <thead>
            <tr>
              <th>recon_id</th><th>When</th><th>RCA mode</th>
              <th className="num">Findings</th><th>Verdict mix</th><th></th>
            </tr>
          </thead>
          <tbody>
            {p.runs.map((r) => {
              const rt = VERDICT_ORDER.reduce((n, v) => n + (r.verdicts[v] || 0), 0);
              return (
                <tr key={r.recon_id} className="clickable" onClick={() => nav(`/runs/${encodeURIComponent(r.recon_id)}`)}>
                  <td style={{ whiteSpace: "nowrap" }}><span className="mono" title={r.recon_id}>{r.recon_id}</span></td>
                  <td>{fmtDate(r.started)}</td>
                  <td>
                    {r.mode === "hybrid" ? (
                      <span className="badge v-migration" style={{ fontSize: 11 }}>🧠 Hybrid</span>
                    ) : r.mode === "deterministic" ? (
                      <span className="badge v-genuine" style={{ fontSize: 11 }}>🧪 Deterministic</span>
                    ) : (
                      <span style={{ color: "var(--muted-2)", fontSize: 12 }}>—</span>
                    )}
                  </td>
                  <td className="num">{r.has_bundle ? r.findings : "—"}</td>
                  <td>
                    {rt === 0 ? (
                      <span style={{ color: "var(--muted-2)", fontSize: 12 }}>{r.has_bundle ? "clean" : "no RCA yet"}</span>
                    ) : (
                      <div style={{ display: "flex", height: 8, width: 130, borderRadius: 4, overflow: "hidden", border: "1px solid var(--border)" }}>
                        {VERDICT_ORDER.map((v) => {
                          const n = r.verdicts[v] || 0;
                          return n ? <div key={v} title={`${p.verdict_meta[v]?.label}: ${n}`} style={{ width: `${(n / rt) * 100}%`, background: VERDICT_COLOR[v] }} /> : null;
                        })}
                      </div>
                    )}
                  </td>
                  <td style={{ color: "var(--muted-2)", fontSize: 12 }}>→</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
