import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { api } from "./api";
import type { AppConfig } from "./types";
import { Layout } from "./components/Layout";
import { HomePage } from "./pages/HomePage";
import { RunsPage } from "./pages/RunsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { TablePage } from "./pages/TablePage";
import { AnalyzePage } from "./pages/AnalyzePage";
import { AuditPage } from "./pages/AuditPage";
import { PortfolioPage } from "./pages/PortfolioPage";
// Trigger Recon removed: ReconResolve is the RCA layer; reconcile is Lakebridge's job.

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  return (
    <Layout config={config}>
      <Routes>
        <Route path="/" element={<HomePage config={config} />} />
        <Route path="/portfolio" element={<PortfolioPage config={config} />} />
        <Route path="/runs" element={<RunsPage config={config} />} />
        <Route path="/audit" element={<AuditPage config={config} />} />
        <Route path="/analyze/:reconId" element={<AnalyzePage />} />
        <Route path="/runs/:reconId" element={<OverviewPage />} />
        <Route path="/runs/:reconId/:table" element={<TablePage />} />
      </Routes>
    </Layout>
  );
}
