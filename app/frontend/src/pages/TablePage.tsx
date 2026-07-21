import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { RunView } from "../types";
import { FindingCard } from "../components/FindingCard";

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
