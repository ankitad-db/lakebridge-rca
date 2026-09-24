import { useState } from "react";
import { getActiveMode, setActiveMode } from "../api";

/** Deterministic ↔ Agentic selector, shown at each point where RCA is run.
 * Writes the shared api mode (also reflected in the sidebar), so the choice applies to the
 * next analyze / analyze-all call. */
export function ModeToggle({ compact }: { compact?: boolean }) {
  const [mode, setMode] = useState<string>(getActiveMode());
  const pick = (m: string) => {
    setActiveMode(m);
    setMode(m);
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, margin: compact ? 0 : "8px 0 14px" }}>
      <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".09em", opacity: 0.6 }}>RCA MODE</span>
      <button
        className={"btn" + (mode === "deterministic" ? " primary" : "")}
        title="Tier-1 only — rule-based, query-confirmed, no LLM"
        onClick={() => pick("deterministic")}
      >
        Deterministic
      </button>
      <button
        className={"btn" + (mode === "agentic" ? " primary" : "")}
        title="Hybrid — deterministic first, then a query-gated Foundation-model fallback on the residual"
        onClick={() => pick("agentic")}
      >
        Hybrid (deterministic + agentic)
      </button>
    </div>
  );
}
