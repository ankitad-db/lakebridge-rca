import type {
  AppConfig,
  AuditRow,
  JobStatus,
  ReconJob,
  ReconRun,
  RunView,
  TableAnalysis,
  TableRef,
} from "./types";

// ---- Active data source (UI-selectable catalog + source dialect) ---------- //
const CATALOG_KEY = "rca.activeCatalog";
const DIALECT_KEY = "rca.activeDialect";
let activeCatalog: string = localStorage.getItem(CATALOG_KEY) || "";
let activeDialect: string = localStorage.getItem(DIALECT_KEY) || "";

export function getActiveCatalog(): string {
  return activeCatalog;
}
export function setActiveCatalog(c: string): void {
  activeCatalog = c || "";
  if (activeCatalog) localStorage.setItem(CATALOG_KEY, activeCatalog);
  else localStorage.removeItem(CATALOG_KEY);
}
export function getActiveDialect(): string {
  return activeDialect;
}
export function setActiveDialect(d: string): void {
  activeDialect = d || "";
  if (activeDialect) localStorage.setItem(DIALECT_KEY, activeDialect);
  else localStorage.removeItem(DIALECT_KEY);
}

function withScope(path: string): string {
  const params: string[] = [];
  if (activeCatalog) params.push(`catalog=${encodeURIComponent(activeCatalog)}`);
  if (activeDialect) params.push(`dialect=${encodeURIComponent(activeDialect)}`);
  if (!params.length) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}${params.join("&")}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(withScope(path));
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(withScope(path), {
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
  catalogs: () => get<{ catalogs: string[] }>("/api/catalogs").then((r) => r.catalogs),
  dialects: () => get<{ dialects: string[] }>("/api/dialects").then((r) => r.dialects),
  runs: () => get<{ runs: ReconRun[] }>("/api/runs").then((r) => r.runs),
  run: (id: string) => get<RunView>(`/api/runs/${encodeURIComponent(id)}`),
  tables: (id: string) =>
    get<{ tables: TableRef[] }>(`/api/runs/${encodeURIComponent(id)}/tables`).then((r) => r.tables),
  analyze: (id: string, table: string) =>
    post<TableAnalysis>(`/api/runs/${encodeURIComponent(id)}/analyze`, { table }),
  analyzeAll: (id: string, drilldown = true, notebook_dir?: string) =>
    post<JobStatus>(`/api/runs/${encodeURIComponent(id)}/analyze-all`, { drilldown, notebook_dir }),
  job: (id: string) => get<JobStatus>(`/api/runs/${encodeURIComponent(id)}/job`),
  summaryUrl: (id: string) => withScope(`/api/runs/${encodeURIComponent(id)}/summary`),
  schemas: () => get<{ schemas: string[] }>("/api/schemas").then((r) => r.schemas),
  schemaTables: (schema: string) =>
    get<{ tables: string[] }>(`/api/schemas/${encodeURIComponent(schema)}/tables`).then((r) => r.tables),
  triggerRecon: (body: unknown) => post<ReconJob>("/api/recon/trigger", body),
  reconJob: (token: string) => get<ReconJob>(`/api/recon/job/${encodeURIComponent(token)}`),
  audit: (limit = 50) =>
    get<{ audit_table: string; rows: AuditRow[] }>(`/api/audit?limit=${limit}`),
};
