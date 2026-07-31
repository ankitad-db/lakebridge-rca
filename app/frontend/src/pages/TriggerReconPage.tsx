import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getActiveCatalog } from "../api";
import type { AppConfig, ReconJob, ReconPairResult } from "../types";

interface Row {
  source: string;
  target: string;
  join_keys: string;
  column_mapping: string;
}

const inputStyle: React.CSSProperties = {
  padding: "8px 10px", borderRadius: 8, fontSize: 13,
  border: "1px solid var(--border-2)", background: "var(--panel-2)", color: "var(--text)",
};

function parsePairs(rows: Row[]) {
  return rows
    .filter((r) => r.source.trim())
    .map((r) => ({
      source: r.source.trim(),
      target: r.target.trim() || r.source.trim(),
      join_keys: r.join_keys.split(",").map((s) => s.trim()).filter(Boolean),
      column_mapping: Object.fromEntries(
        r.column_mapping
          .split(",")
          .map((s) => s.split(":").map((x) => x.trim()))
          .filter((kv) => kv.length === 2 && kv[0] && kv[1]),
      ),
    }));
}

function PairResultRow({ p }: { p: ReconPairResult }) {
  const ok = p.status === "ok";
  const diffs = p.missing_in_target || p.missing_in_source || p.absolute_mismatch || !p.schema_ok;
  return (
    <tr>
      <td className="mono">{p.source_table}{p.target_table !== p.source_table ? ` → ${p.target_table}` : ""}</td>
      <td>
        {ok ? (
          diffs ? <span className="badge v-migration">⚠️ diffs</span> : <span className="badge v-benign">✅ match</span>
        ) : (
          <span className="badge v-review">✗ error</span>
        )}
      </td>
      <td className="mono" style={{ fontSize: 12 }}>
        {p.join_keys.length ? p.join_keys.join(", ") : "—"}
        {p.keys_origin && <div className="muted" style={{ fontSize: 11 }}>{p.keys_origin}</div>}
      </td>
      <td className="num">{ok ? `${p.source_count} → ${p.target_count}` : "—"}</td>
      <td className="num">{ok ? (p.missing_in_target + p.missing_in_source) : "—"}</td>
      <td style={{ fontSize: 12 }}>
        {ok ? (p.mismatch_columns.length ? p.mismatch_columns.join(", ") : "—") : (
          <span className="muted" style={{ color: "var(--lava-2)" }}>{p.message}</span>
        )}
      </td>
    </tr>
  );
}

export function TriggerReconPage({ config }: { config: AppConfig | null }) {
  const nav = useNavigate();
  const [srcSchema, setSrcSchema] = useState("");
  const [tgtSchema, setTgtSchema] = useState("");
  const [schemas, setSchemas] = useState<string[]>([]);
  const [srcTables, setSrcTables] = useState<string[] | null>(null);
  const [rows, setRows] = useState<Row[]>([{ source: "", target: "", join_keys: "", column_mapping: "" }]);
  const [autoAnalyze, setAutoAnalyze] = useState(true);
  const [nbDir, setNbDir] = useState("");
  const [job, setJob] = useState<ReconJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const poll = useRef<number | null>(null);

  useEffect(() => {
    if (config) {
      setSrcSchema((s) => s || config.source_schema || "");
      setTgtSchema((s) => s || config.target_schema || "");
      setNbDir((s) => s || config.notebook_dir || "");
    }
    api.schemas().then(setSchemas).catch(() => undefined);
    return () => { if (poll.current) window.clearInterval(poll.current); };
  }, [config]);

  const running = job?.state === "running";

  function loadTables() {
    if (!srcSchema.trim()) return;
    setSrcTables(null);
    api.schemaTables(srcSchema.trim()).then(setSrcTables).catch((e) => setError(String(e.message || e)));
  }

  function toggleTable(name: string, checked: boolean) {
    setRows((rs) => {
      const others = rs.filter((r) => r.source !== name);
      if (checked) return [...others.filter((r) => r.source), { source: name, target: "", join_keys: "", column_mapping: "" }];
      const kept = others.filter((r) => r.source);
      return kept.length ? kept : [{ source: "", target: "", join_keys: "", column_mapping: "" }];
    });
  }

  const selected = useMemo(() => new Set(rows.map((r) => r.source).filter(Boolean)), [rows]);

  function updateRow(i: number, patch: Partial<Row>) {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }
  function addRow() {
    setRows((rs) => [...rs, { source: "", target: "", join_keys: "", column_mapping: "" }]);
  }
  function removeRow(i: number) {
    setRows((rs) => (rs.length > 1 ? rs.filter((_, idx) => idx !== i) : rs));
  }

  function startPolling(token: string) {
    if (poll.current) window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      try {
        const j = await api.reconJob(token);
        setJob(j);
        if (j.state === "done" || j.state === "error") {
          if (poll.current) window.clearInterval(poll.current);
        }
      } catch {
        /* keep polling */
      }
    }, 1500);
  }

  async function trigger() {
    setError(null);
    const pairs = parsePairs(rows);
    if (!pairs.length) { setError("Add at least one source table."); return; }
    const body = {
      source_schema: srcSchema.trim(),
      target_schema: tgtSchema.trim(),
      tables: pairs,
      auto_analyze: autoAnalyze,
      notebook_dir: nbDir.trim() || undefined,
    };
    try {
      const j = await api.triggerRecon(body);
      setJob(j);
      if (j.state === "error") { setError(j.message || "Failed to start."); return; }
      if (j.token) startPolling(j.token);
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }

  const pct = job?.total ? Math.round((100 * (job.done || 0)) / job.total) : 0;

  return (
    <>
      <div className="topbar">
        <div>
          <div className="title">Trigger a reconciliation</div>
          <div className="subtitle">
            Compare source vs. migrated target on the warehouse — join keys are auto-detected when
            you don't supply them, renamed columns are handled via a mapping, and a failing pair is
            isolated (never sinks the run). A fresh <span className="mono">recon_id</span> is created
            and the RCA runs automatically.
          </div>
        </div>
        {config?.demo_mode && <span className="demo-pill">DEMO · no warehouse</span>}
      </div>

      {config && !config.has_warehouse && (
        <div className="panel" style={{ borderColor: "var(--lava)", marginBottom: 16 }}>
          ⚠️ No warehouse configured — triggering a reconcile needs a SQL warehouse (set
          <code> RCA_WAREHOUSE_ID</code>).
        </div>
      )}

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3>1 · Schemas</h3>
        <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>Source schema (catalog {getActiveCatalog() || config?.recon_catalog})</span>
            <input list="schemas" style={{ ...inputStyle, width: 240 }} value={srcSchema}
                   onChange={(e) => setSrcSchema(e.target.value)} placeholder="mig_source_sim" />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>Target schema</span>
            <input list="schemas" style={{ ...inputStyle, width: 240 }} value={tgtSchema}
                   onChange={(e) => setTgtSchema(e.target.value)} placeholder="mig_target" />
          </label>
          <datalist id="schemas">
            {schemas.map((s) => <option key={s} value={s} />)}
          </datalist>
          <button className="btn" onClick={loadTables} disabled={!srcSchema.trim()}>List source tables</button>
        </div>

        {srcTables && (
          <div style={{ marginTop: 12 }}>
            <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
              Tick tables to reconcile ({selected.size} selected):
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {srcTables.map((t) => (
                <label key={t} className="pill" style={{ cursor: "pointer", display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={selected.has(t)} onChange={(e) => toggleTable(t, e.target.checked)} />
                  <span className="mono">{t}</span>
                </label>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3>2 · Table pairs</h3>
        <table>
          <thead>
            <tr>
              <th>Source table</th>
              <th>Target (optional)</th>
              <th>Join keys (optional, comma)</th>
              <th>Column map (optional, src:tgt)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td><input style={{ ...inputStyle, width: "100%" }} value={r.source} placeholder="fact_orders"
                           onChange={(e) => updateRow(i, { source: e.target.value })} /></td>
                <td><input style={{ ...inputStyle, width: "100%" }} value={r.target} placeholder="(= source)"
                           onChange={(e) => updateRow(i, { target: e.target.value })} /></td>
                <td><input style={{ ...inputStyle, width: "100%" }} value={r.join_keys} placeholder="auto-detect"
                           onChange={(e) => updateRow(i, { join_keys: e.target.value })} /></td>
                <td><input style={{ ...inputStyle, width: "100%" }} value={r.column_mapping} placeholder="country:country_name"
                           onChange={(e) => updateRow(i, { column_mapping: e.target.value })} /></td>
                <td className="num"><button className="btn" onClick={() => removeRow(i)}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 10 }}><button className="btn" onClick={addRow}>+ Add row</button></div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3>3 · Run</h3>
        <div className="row" style={{ gap: 16, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="checkbox" checked={autoAnalyze} onChange={(e) => setAutoAnalyze(e.target.checked)} />
            <span>Run RCA + publish notebooks automatically</span>
          </label>
          <input style={{ ...inputStyle, width: 320 }} value={nbDir} onChange={(e) => setNbDir(e.target.value)}
                 placeholder="notebook target folder (optional)" title="Workspace folder for published notebooks" />
          <button className="btn primary" onClick={trigger} disabled={running || (config != null && !config.has_warehouse)}>
            {running ? "Running…" : "▶ Trigger reconcile & RCA"}
          </button>
        </div>
      </div>

      {error && <div className="panel" style={{ borderColor: "var(--lava)", marginBottom: 16 }}>⚠️ {error}</div>}

      {job && job.state !== "idle" && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <h3 style={{ margin: 0 }}>
              {job.phase === "reconciling" && "🔄 Reconciling…"}
              {job.phase === "analyzing" && "🧠 Running RCA…"}
              {(job.state === "done") && "✅ Complete"}
              {(job.state === "error") && "⚠️ Failed"}
            </h3>
            {job.recon_id && (
              <span className="mono muted" style={{ fontSize: 12 }}>recon_id: {job.recon_id}</span>
            )}
          </div>

          {running && (
            <div style={{ height: 8, borderRadius: 6, background: "var(--panel-2)", overflow: "hidden", marginBottom: 10 }}>
              <div style={{ width: `${job.phase === "analyzing" ? 100 : pct}%`, height: "100%", background: "var(--lava)", transition: "width .3s" }} />
            </div>
          )}
          <div className="muted" style={{ marginBottom: 12 }}>{job.message}</div>

          {job.pairs && job.pairs.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Pair</th><th>Result</th><th>Join keys</th>
                  <th className="num">Rows (s→t)</th><th className="num">Missing</th><th>Mismatch cols / error</th>
                </tr>
              </thead>
              <tbody>{job.pairs.map((p, i) => <PairResultRow key={i} p={p} />)}</tbody>
            </table>
          )}

          {job.recon_id && (job.state === "done" || job.phase === "analyzing") && (
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
              <button className="btn primary" onClick={() => nav(`/runs/${encodeURIComponent(job.recon_id!)}`)}>
                📊 Open dashboard
              </button>
              <button className="btn" onClick={() => nav(`/analyze/${encodeURIComponent(job.recon_id!)}`)}>
                Analyze table-by-table
              </button>
              {job.notebook_url && (
                <a className="btn" href={job.notebook_url} target="_blank" rel="noreferrer">📓 Open notebooks</a>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}
