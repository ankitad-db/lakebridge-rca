import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import type { AppConfig } from "../types";
import {
  api,
  getActiveCatalog,
  getActiveDialect,
  setActiveCatalog,
  setActiveDialect,
} from "../api";

export function Layout({ config, children }: { config: AppConfig | null; children: ReactNode }) {
  const loc = useLocation();
  const onDashboard = /^\/runs\/.+/.test(loc.pathname);
  const [catalogs, setCatalogs] = useState<string[]>([]);
  const [catalog, setCatalog] = useState<string>(getActiveCatalog());
  const [dialects, setDialects] = useState<string[]>([]);
  const [dialect, setDialect] = useState<string>(getActiveDialect());

  useEffect(() => {
    // Seed the active catalog/dialect from config the first time (if not chosen yet).
    if (config?.recon_catalog && !getActiveCatalog()) {
      setActiveCatalog(config.recon_catalog);
      setCatalog(config.recon_catalog);
    }
    if (config?.dialect && !getActiveDialect()) {
      setActiveDialect(config.dialect);
      setDialect(config.dialect);
    }
    api.catalogs().then(setCatalogs).catch(() => undefined);
    api.dialects().then(setDialects).catch(() => undefined);
  }, [config]);

  function changeCatalog(c: string) {
    setActiveCatalog(c);
    setCatalog(c);
    // A catalog switch changes every data source; reload so all views re-fetch cleanly.
    window.location.assign("/");
  }

  function changeDialect(d: string) {
    setActiveDialect(d);
    setDialect(d);
    window.location.assign("/");
  }

  const current = catalog || config?.recon_catalog || "";
  const options = Array.from(new Set([current, ...catalogs].filter(Boolean)));
  const curDialect = dialect || config?.dialect || "";
  const dialectOptions = Array.from(new Set([curDialect, ...dialects].filter(Boolean)));

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo" />
          <div>
            <div className="name">ReconResolve</div>
            <div className="sub">Post-Lakebridge RCA</div>
          </div>
        </div>

        {!config?.demo_mode && (
          <label className="catalog-pick">
            <span className="lbl">CATALOG</span>
            <select value={current} onChange={(e) => changeCatalog(e.target.value)}>
              {options.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
        )}

        <label className="catalog-pick">
          <span className="lbl">SOURCE DIALECT</span>
          <select value={curDialect} onChange={(e) => changeDialect(e.target.value)}>
            {dialectOptions.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </label>

        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            🏠 Overview
          </NavLink>
          <NavLink to="/trigger" className={({ isActive }) => (isActive ? "active" : "")}>
            ⚡ Trigger recon
          </NavLink>
          <NavLink to="/runs" className={({ isActive }) => (isActive ? "active" : "")}>
            📥 Recon runs
          </NavLink>
          <a className={onDashboard ? "active" : ""} style={{ opacity: onDashboard ? 1 : 0.5 }}>
            📊 Run dashboard
          </a>
          <NavLink to="/audit" className={({ isActive }) => (isActive ? "active" : "")}>
            🧾 Audit trail
          </NavLink>
        </nav>

        <div className="foot">
          {config?.demo_mode ? "Demo mode · bundled sample" : `${current}.${config?.recon_schema}`}
          <br />
          dialect: {config?.dialect || "—"}
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
