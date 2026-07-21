import type { Severity, Verdict } from "../types";

const VERDICT_CLASS: Record<Verdict, string> = {
  migration_induced: "v-migration",
  genuine_data: "v-genuine",
  benign: "v-benign",
  needs_review: "v-review",
};

const VERDICT_ICON: Record<Verdict, string> = {
  migration_induced: "🔧",
  genuine_data: "📊",
  benign: "✅",
  needs_review: "🔍",
};

const VERDICT_LABEL: Record<Verdict, string> = {
  migration_induced: "Migration-induced",
  genuine_data: "Genuine data",
  benign: "Benign",
  needs_review: "Needs review",
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`badge ${VERDICT_CLASS[verdict]}`}>
      {VERDICT_ICON[verdict]} {VERDICT_LABEL[verdict]}
    </span>
  );
}

export function SeverityBadge({ severity, score }: { severity: Severity; score?: number }) {
  return (
    <span className={`badge sev-${severity}`}>
      {severity}
      {score !== undefined ? ` · ${score}` : ""}
    </span>
  );
}

export function MatchBar({ pct }: { pct: number }) {
  const cls = pct >= 99 ? "" : pct >= 80 ? "mid" : "low";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div className={`mbar ${cls}`}>
        <span style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
      </div>
      <span className="mono" style={{ fontSize: 12, minWidth: 52, textAlign: "right" }}>
        {pct.toFixed(2)}%
      </span>
    </div>
  );
}
