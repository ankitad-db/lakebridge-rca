import type { FindingView } from "../types";

/** The migrated (target) transform expression + its script location, from the code evidence. */
function targetTransform(f: FindingView): { expr: string; loc: string | null } | null {
  for (const e of f.evidence) {
    if (e.label !== "code" && e.label !== "code_generated") continue;
    if (!/derivation:/i.test(e.detail)) continue;
    const expr = e.detail.match(/`([^`]+)`/);
    const loc = e.detail.match(/\[in\s+([^\]]+)\]/i);
    if (expr) return { expr: expr[1], loc: loc ? loc[1].trim() : null };
  }
  return null;
}

/** The SOURCE EDW derivation expression, from the source_code evidence. */
function sourceExpr(f: FindingView): string | null {
  for (const e of f.evidence) {
    if (e.label !== "source_code") continue;
    const m = e.detail.match(/`([^`]+)`/);
    if (m) return m[1];
  }
  return null;
}

/** A row-count cause (load filter / watermark) for a table-level volume finding. */
function loadFilter(f: FindingView): string | null {
  for (const e of f.evidence) {
    if (e.label === "code" && /load filter|filter|watermark/i.test(e.detail)) {
      const m = e.detail.match(/`([^`]+)`/);
      if (m) return m[1];
    }
  }
  return null;
}

/** Whether a lineage flow will render — FindingCard uses this to drop the now-redundant text evidence. */
export function hasLineageFlow(f: FindingView): boolean {
  if (f.column) return !!(targetTransform(f) || sourceExpr(f));
  return f.total_count > 0 && f.mismatch_count > 0;
}

const VERDICT_ACCENT: Record<string, string> = {
  migration_induced: "var(--lava)",
  genuine_data: "var(--blue)",
  benign: "var(--green)",
  needs_review: "var(--amber)",
};

// Friendly source-system names for the dialect the recon came from.
const DIALECT_NAME: Record<string, string> = {
  snowflake: "Snowflake", oracle: "Oracle", mssql: "SQL Server", synapse: "Synapse",
  redshift: "Redshift", teradata: "Teradata", databricks: "Databricks",
};
const sourceLabel = (d: string) => `Source · ${DIALECT_NAME[d] || (d ? d[0].toUpperCase() + d.slice(1) : "EDW")} EDW`;

function Note({ f }: { f: FindingView }) {
  return (
    <div className="linflow-note">
      <span><b>🔧 The defect lives in the migrated transform</b> — the source (EDW) is the baseline.</span>
      {f.confirmed && <span className="ok">✔ query-confirmed</span>}
    </div>
  );
}

/**
 * Derivation as blocks: SOURCE (EDW logic) → the migrated TRANSFORM (the culprit) → TARGET.
 *  - column findings: source table/expr → migrated expression + script → target column;
 *  - table-level volume findings: source rows → load filter/watermark → target rows (delta).
 */
export function LineageFlow({ f }: { f: FindingView }) {
  const accent = VERDICT_ACCENT[f.verdict] || "var(--amber)";

  // ── Column finding: source logic → migrated transform → target column ──
  if (f.column) {
    const tgt = targetTransform(f);
    const src = sourceExpr(f);
    if (!tgt && !src) return null;
    const rowsAffected =
      f.total_count > 0 && f.mismatch_count > 0
        ? `${f.mismatch_count.toLocaleString()} of ${f.total_count.toLocaleString()} rows`
        : null;
    return (
      <>
        <div className="k muted" style={{ marginBottom: 6 }}>Lineage — source logic vs. migrated logic</div>
        <div className="linflow">
          <div className="linflow-block src">
            <span className="kicker">{sourceLabel(f.dialect)}</span>
            <span className="name">{f.source_ref}.{f.column}</span>
            {src ? <span className="code">{src}</span> : <span className="sub">baseline value</span>}
          </div>
          <span className="linflow-arrow">→</span>
          <div className="linflow-block xform">
            <span className="kicker">🔧 Migrated transform</span>
            {tgt ? <span className="code">{tgt.expr}</span> : <span className="sub">migration-produced value</span>}
            {tgt?.loc && <span className="sub">📄 {tgt.loc}</span>}
          </div>
          <span className="linflow-arrow">→</span>
          <div className="linflow-block tgt" style={{ borderLeftColor: accent }}>
            <span className="kicker">Target · Databricks ⚠</span>
            <span className="name">{f.target_ref}.{f.column}</span>
            {rowsAffected && <span className="sub">{rowsAffected}</span>}
          </div>
        </div>
        <Note f={f} />
      </>
    );
  }

  // ── Table-level volume finding: source rows → load filter → target rows (delta) ──
  const filter = loadFilter(f);
  if (f.total_count > 0 && f.mismatch_count > 0) {
    const tgtRows = Math.max(f.total_count - f.mismatch_count, 0);
    return (
      <>
        <div className="k muted" style={{ marginBottom: 6 }}>Lineage — where the rows went</div>
        <div className="linflow">
          <div className="linflow-block src">
            <span className="kicker">{sourceLabel(f.dialect)}</span>
            <span className="name">{f.source_ref || f.table}</span>
            <span className="sub">{f.total_count.toLocaleString()} rows</span>
          </div>
          <span className="linflow-arrow">→</span>
          <div className="linflow-block xform">
            <span className="kicker">🔧 Migrated load</span>
            {filter ? <span className="code">{filter}</span> : <span className="sub">load filter / watermark</span>}
          </div>
          <span className="linflow-arrow">→</span>
          <div className="linflow-block tgt" style={{ borderLeftColor: accent }}>
            <span className="kicker">Target · Databricks ⚠</span>
            <span className="name">{f.target_ref || f.table}</span>
            <span className="sub">{tgtRows.toLocaleString()} rows · {f.mismatch_count.toLocaleString()} missing</span>
          </div>
        </div>
        <Note f={f} />
      </>
    );
  }

  return null;
}
