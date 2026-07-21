import type { AppConfig, JobStatus, ReconRun, RunView, TableAnalysis, TableRef } from "./types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new Error((b as { detail?: string }).detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  config: () => get<AppConfig>("/api/config"),
  runs: () => get<{ runs: ReconRun[] }>("/api/runs").then((r) => r.runs),
  run: (id: string) => get<RunView>(`/api/runs/${encodeURIComponent(id)}`),
  tables: (id: string) =>
    get<{ tables: TableRef[] }>(`/api/runs/${encodeURIComponent(id)}/tables`).then((r) => r.tables),
  analyze: (id: string, table: string) =>
    post<TableAnalysis>(`/api/runs/${encodeURIComponent(id)}/analyze`, { table }),
  analyzeAll: (id: string, drilldown = true, notebook_dir?: string) =>
    post<JobStatus>(`/api/runs/${encodeURIComponent(id)}/analyze-all`, { drilldown, notebook_dir }),
  job: (id: string) => get<JobStatus>(`/api/runs/${encodeURIComponent(id)}/job`),
  summaryUrl: (id: string) => `/api/runs/${encodeURIComponent(id)}/summary`,
};
