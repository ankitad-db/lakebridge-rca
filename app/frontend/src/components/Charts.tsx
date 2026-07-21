import type { RunView } from "../types";

const COLORS: Record<string, string> = {
  migration_induced: "#ff3621",
  genuine_data: "#2d9bf0",
  needs_review: "#e8a317",
  benign: "#16a97a",
};

const ORDER = ["migration_induced", "genuine_data", "needs_review", "benign"];

export function VerdictDonut({ view }: { view: RunView }) {
  const counts = view.verdict_counts;
  const total = ORDER.reduce((a, k) => a + (counts[k] || 0), 0);
  let acc = 0;
  const stops: string[] = [];
  ORDER.forEach((k) => {
    const n = counts[k] || 0;
    if (n === 0) return;
    const start = (acc / total) * 360;
    acc += n;
    const end = (acc / total) * 360;
    stops.push(`${COLORS[k]} ${start}deg ${end}deg`);
  });
  const bg = total > 0 ? `conic-gradient(${stops.join(", ")})` : "var(--panel-2)";
  return (
    <div className="row" style={{ alignItems: "center", gap: 22 }}>
      <div className="donut" style={{ background: bg }}>
        <div className="center">
          <div>
            <div style={{ fontSize: 26, fontWeight: 750 }}>{total}</div>
            <div className="muted" style={{ fontSize: 11 }}>findings</div>
          </div>
        </div>
      </div>
      <div className="legend spread">
        {ORDER.map((k) => (
          <div className="item" key={k}>
            <span className="dot" style={{ background: COLORS[k] }} />
            {view.verdict_meta[k]?.icon} {view.verdict_meta[k]?.label}
            <b>{counts[k] || 0}</b>
          </div>
        ))}
      </div>
    </div>
  );
}
