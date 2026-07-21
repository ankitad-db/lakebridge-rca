import type { AppConfig, ReconRun, RunView } from "./types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  config: () => get<AppConfig>("/api/config"),
  runs: () => get<{ runs: ReconRun[] }>("/api/runs").then((r) => r.runs),
  run: (id: string) => get<RunView>(`/api/runs/${encodeURIComponent(id)}`),
  summaryUrl: (id: string) => `/api/runs/${encodeURIComponent(id)}/summary`,
};
