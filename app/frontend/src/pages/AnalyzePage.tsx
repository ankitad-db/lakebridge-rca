import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { TableAnalysis, TableRef } from "../types";
import { FindingCard } from "../components/FindingCard";

const VERDICT_CLASS: Record<string, string> = {
  migration_induced: "v-migration",
  genuine_data: "v-genuine",
  benign: "v-benign",
  needs_review: "v-review",
};

function ResultPanel({ res }: { res: TableAnalysis }) {
  const s = res.summary;
  return (
    <div className="section">
      <div className="row" style={{ gap: 10, marginBottom: 12 }}>
        {Object.entries(res.verdict_counts).map(([k, n]) => (
          <span key={k} className={`badge ${VERDICT_CLASS[k] || "pill"}`}>
            {res.verdict_meta[k]?.icon} {res.verdict_meta[k]?.label}: {n}
          </span>
        ))}
        {s && (
          <span className="pill">
            {s.source_count.toLocaleString()} → {s.target_count.toLocaleString()} rows · row match{" "}
            {s.row_match_pct.toFixed(2)}%
          </span>
        )}
      </div>
      {res.clean ? (
        <div className="panel center-msg">✅ No findings — this table reconciles cleanly.</div>
      ) : (
        res.findings.map((f) => <FindingCard key={f.location} f={f} />)
      )}
    </div>
  );
}

export function AnalyzePage() {
  const { reconId = "" } = useParams();
  const nav = useNavigate();
  const [tables, setTables] = useState<TableRef[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, TableAnalysis>>({});
  const [rowError, setRowError] = useState<Record<string, string>>({});

  useEffect(() => {
    api.tables(reconId).then(setTables).catch((e) => setError(String(e.message || e)));
  }, [reconId]);

  async function runOne(name: string) {
    setSelected(name);
    setRunning(name);
    setRowError((m) => ({ ...m, [name]: "" }));
    try {
      const res = await api.analyze(reconId, name);
      setResults((m) => ({ ...m, [name]: res }));
      setTables((ts) => ts && ts.map((t) => (t.name === name ? { ...t, analyzed: true } : t)));
    } catch (e) {
      setRowError((m) => ({ ...m, [name]: String((e as Error).message || e) }));
    } finally {
      setRunning(null);
    }
  }

  if (error) return <div className="panel" style={{ borderColor: "var(--lava)" }}>⚠️ {error}</div>;

  return (
    <>
      <div className="crumbs">
        <Link to="/">Recon runs</Link> / <span className="mono">{reconId}</span> / analyze
      </div>
      <div className="topbar">
        <div>
          <div className="title">Run RCA — one table at a time</div>
          <div className="subtitle">
            Runs the same engine the Genie skill runs (ingest → classify → live drill-down) for the
            table you pick. Analyzed tables also update the{" "}
            <Link to={`/runs/${encodeURIComponent(reconId)}`}>run dashboard</Link>.
          </div>
        </div>
        <button className="btn primary" onClick={() => nav(`/runs/${encodeURIComponent(reconId)}`)}>
          ▶ Run full RCA & generate notebook
        </button>
      </div>

      {!tables ? (
        <div className="center-msg"><div className="spinner" /></div>
      ) : (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Table</th>
                <th>Recon signal</th>
                <th>RCA status</th>
                <th style={{ width: 180 }}></th>
              </tr>
            </thead>
            <tbody>
              {tables.map((t) => {
                const done = !!results[t.name] || t.analyzed;
                const isRunning = running === t.name;
                return (
                  <tr
                    key={t.name}
                    className="clickable"
                    onClick={() => setSelected(t.name)}
                    style={selected === t.name ? { background: "rgba(255,54,33,0.06)" } : undefined}
                  >
                    <td className="mono">{t.name}</td>
                    <td>
                      {t.has_diffs === false ? (
                        <span className="badge v-benign">✅ no diffs</span>
                      ) : t.has_diffs ? (
                        <span className="badge v-migration">⚠️ has diffs</span>
                      ) : (
                        <span className="pill">unknown</span>
                      )}
                    </td>
                    <td>
                      {isRunning ? (
                        <span className="badge v-review">⏳ running…</span>
                      ) : done ? (
                        <span className="badge v-benign">✓ analyzed</span>
                      ) : (
                        <span className="muted">not analyzed</span>
                      )}
                      {rowError[t.name] && (
                        <div className="muted" style={{ color: "var(--lava-2)", fontSize: 12 }}>
                          {rowError[t.name]}
                        </div>
                      )}
                    </td>
                    <td className="num">
                      <button
                        className={`btn ${done ? "" : "primary"}`}
                        disabled={isRunning}
                        onClick={(e) => {
                          e.stopPropagation();
                          runOne(t.name);
                        }}
                      >
                        {isRunning ? "Running…" : done ? "Re-run" : "▶ Run RCA"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="section">
          <h2 className="mono" style={{ fontSize: 18 }}>{selected}</h2>
          {running === selected ? (
            <div className="panel center-msg">
              <div>
                <div className="spinner" style={{ margin: "0 auto 10px" }} />
                Running RCA on <code>{selected}</code> — ingest → classify → live drill-down…
              </div>
            </div>
          ) : results[selected] ? (
            <ResultPanel res={results[selected]} />
          ) : (
            <div className="panel center-msg">
              <button className="btn primary" onClick={() => runOne(selected)}>
                ▶ Run RCA for {selected}
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
