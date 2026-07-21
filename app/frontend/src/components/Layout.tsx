import { NavLink, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import type { AppConfig } from "../types";

export function Layout({ config, children }: { config: AppConfig | null; children: ReactNode }) {
  const loc = useLocation();
  const onRun = loc.pathname.startsWith("/runs/");
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo" />
          <div>
            <div className="name">RCA Genie</div>
            <div className="sub">Post-Lakebridge RCA</div>
          </div>
        </div>
        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            📥 Recon runs
          </NavLink>
          <NavLink to="/trigger" className={({ isActive }) => (isActive ? "active" : "")}>
            ⚡ Trigger recon
          </NavLink>
          <a className={onRun ? "active" : ""} style={{ opacity: onRun ? 1 : 0.5 }}>
            📊 Run dashboard
          </a>
        </nav>
        <div className="foot">
          {config?.demo_mode ? "Demo mode · bundled sample" : `Source: ${config?.recon_catalog}.${config?.recon_schema}`}
          <br />
          dialect: {config?.dialect || "—"}
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
