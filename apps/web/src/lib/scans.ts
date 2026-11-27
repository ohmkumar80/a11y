export type ScanStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
export type Severity = "critical" | "serious" | "moderate" | "minor";
export type Kind = "violation" | "needs_review" | "best_practice";

export interface ScanRow {
  id: string; url: string; mode: "single" | "crawl"; max_pages: number; standards: string[]; status: ScanStatus;
  error_code: string | null; error_detail: string | null; pages_scanned: number; findings_count: number;
  created_at: string; started_at: string | null; finished_at: string | null;
}
export interface ScanDetail extends ScanRow {
  engine_versions: Record<string, string>; rules_version: string | null; attempts: number;
  pages: Array<{ id: string; url: string; status: string; error_detail: string | null; title: string | null }>;
  by_kind: Partial<Record<Kind, Partial<Record<Severity, number>>>>;
  summary: Summary;
}
export interface Summary {
  standard: string; label: string; legal_status: string; citation: string | null; notes: string | null;
  automated_coverage: { tested: number; total: number };
  failed: string[]; needs_review: string[]; no_issues_found: string[]; not_tested: string[];
  review_status: string; disclaimer: string;
}
export interface Finding {
  id: string; rule: string; title: string; kind: Kind; severity: Severity; confidence: "high" | "medium" | "low" | "review";
  criteria: Array<{ id: string; name: string; level: string; clause: string }>;
  engines: string[]; agreement: string; message: string; element: { xpath: string; css: string; tag: string; html: string };
  page: { id: string; url: string }; help_url: string | null;
}
export interface Cluster {
  cluster_key: string; rule: string; title: string; sc: string[]; occurrences: number; pages: number; severity: Severity;
  sample: { id: string; html: string; css: string };
}
export interface StandardInfo { id: string; label: string; legal_status: string; criteria_count: number; automated_criteria: number; citation: string | null }

export const STATUS_LABEL: Record<ScanStatus, string> = {
  QUEUED: "Waiting to start", RUNNING: "Scanning", SUCCEEDED: "Done", FAILED: "Failed", CANCELLED: "Cancelled",
};
export const SEVERITY_LABEL: Record<Severity, string> = { critical: "Critical", serious: "Serious", moderate: "Moderate", minor: "Minor" };
export const SEVERITY_ICON: Record<Severity, string> = { critical: "▲▲", serious: "▲", moderate: "●", minor: "○" };
export const KIND_LABEL: Record<Kind, string> = { violation: "Failures", needs_review: "Needs review", best_practice: "Best practices" };
export const CONFIDENCE_LABEL: Record<Finding["confidence"], string> = {
  high: "High confidence", medium: "Medium: only one engine checks this", low: "Low: other engines did not flag it", review: "Needs your judgement",
};
export const LEGAL_LABEL: Record<string, string> = {
  regulation: "Legal requirement", benchmark: "Benchmark (not a legal requirement)", recommended_target: "Recommended target (not a legal requirement)",
  reference: "Reference standard", informational: "Informational",
};
export const isActive = (s: ScanStatus) => s === "QUEUED" || s === "RUNNING";
