import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { api } from "./api";
import type { AppConfig } from "./types";
import { Layout } from "./components/Layout";
import { RunsPage } from "./pages/RunsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { TablePage } from "./pages/TablePage";

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  return (
    <Layout config={config}>
      <Routes>
        <Route path="/" element={<RunsPage config={config} />} />
        <Route path="/runs/:reconId" element={<OverviewPage />} />
        <Route path="/runs/:reconId/:table" element={<TablePage />} />
      </Routes>
    </Layout>
  );
}
