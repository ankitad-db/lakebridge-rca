export interface AppConfig {
  recon_catalog: string;
  recon_schema: string;
  dialect: string;
  has_warehouse: boolean;
  allow_ondemand: boolean;
  in_app: boolean;
  demo_mode: boolean;
  workspace_host: string;
  notebook_dir: string;
}

export interface JobStatus {
  state: "idle" | "running" | "done" | "error";
  message?: string;
  notebook_path?: string | null;
  notebook_url?: string | null;
  tables?: number;
  findings?: number;
}

export interface ReconRun {
  recon_id: string;
  title?: string | null;
  source?: string | null;
  started: string | null;
  ended: string | null;
  table_pairs: number;
  tables_with_diffs: number;
  clean: boolean;
  has_bundle?: boolean;
}

export interface Evidence {
  label: string;
  detail: string;
  query: string | null;
}

export interface Sample {
  keys: Record<string, unknown>;
  source: unknown;
  target: unknown;
}

export type Verdict = "migration_induced" | "genuine_data" | "benign" | "needs_review";
export type Severity = "High" | "Medium" | "Low";

export interface FindingView {
  location: string;
  table: string;
  column: string | null;
  recon_type: string;
  mismatch_count: number;
  total_count: number;
  match_pct: number | null;
  category: string | null;
  verdict: Verdict;
  confidence: number;
  confirmed: boolean;
  severity: Severity;
  severity_score: number;
  rationale: string;
  remediation: string;
  owner: string;
  evidence: Evidence[];
  samples: Sample[];
}

export interface TableView {
  name: string;
  source_table: string;
  target_table: string;
  source_count: number;
  target_count: number;
  missing_in_target: number;
  missing_in_source: number;
  absolute_mismatch: number;
  row_match_pct: number;
  schema_ok: boolean;
  findings_count: number;
  verdicts: Record<string, number>;
  max_severity: Severity | null;
  max_severity_score: number;
  clean: boolean;
}

export interface TableRef {
  name: string;
  source_table: string;
  target_table: string;
  has_diffs: boolean | null;
  analyzed: boolean;
}

export interface TableSummaryView {
  source_table: string;
  target_table: string;
  source_count: number;
  target_count: number;
  missing_in_target: number;
  missing_in_source: number;
  absolute_mismatch: number;
  row_match_pct: number;
  schema_ok: boolean;
}

export interface NotebookRef {
  notebook_path?: string;
  notebook_url?: string | null;
  notebook_folder?: string;
  notebook_error?: string;
}

export interface TableAnalysis {
  recon_id: string;
  table: string;
  verdict_meta: Record<string, { icon: string; label: string; action: string }>;
  verdict_counts: Record<string, number>;
  summary: TableSummaryView | null;
  clean: boolean;
  findings: FindingView[];
  notebook?: NotebookRef;
}

export interface RunView {
  recon_id: string;
  dialect: string;
  verdict_counts: Record<string, number>;
  verdict_meta: Record<string, { icon: string; label: string; action: string }>;
  overall_row_match_pct: number;
  table_pairs: number;
  findings_total: number;
  top_priorities: FindingView[];
  tables: TableView[];
  findings: FindingView[];
}
