export interface DocumentRow {
  id: string;
  filename: string;
  kind: "pdf" | "docx" | "pptx" | "epub";
  size_bytes: number;
  status: "UPLOADED" | "SCANNING" | "CLEAN" | "REJECTED" | "FAILED";
  reject_detail: string | null;
  page_count: number | null;
  created_at: string;
  expires_at: string;
  ready: boolean;
  latest_audit: AuditRow | null;
  derived_from: string | null;
}

export type AuditStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";

export interface AuditSummary {
  standard: string;
  verdict: "problems_found" | "no_automated_problems";
  findings: number;
  by_severity: Record<"critical" | "serious" | "moderate" | "minor", number>;
  needs_a_person: number;
  rules_passed: number;
  rules_failed: number;
  caveat: string;
  facts: { pages: number; tagged: boolean; has_structure: boolean; language: string | null; has_title: boolean; has_bookmarks: boolean; image_only_pages: number };
}

export interface AuditRow {
  id: string;
  document_id: string;
  status: AuditStatus;
  pages: number;
  summary: Partial<AuditSummary>;
  error_code: string | null;
  error_detail: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface DocFinding {
  id: string;
  rule_id: string;
  source: "verapdf" | "direct";
  severity: "critical" | "serious" | "moderate" | "minor";
  title: string;
  explanation: string;
  how_to_fix: string;
  wcag: string[];
  needs_human: boolean;
  count: number;
  pages: number[];
  pages_total: number;
  examples: { where: string; message: string }[];
  explained: boolean;
}

export interface AuditDetail extends AuditRow {
  document: { id: string; filename: string; kind: string; page_count: number | null };
  findings: DocFinding[];
}

export const auditActive = (s?: AuditStatus) => s === "QUEUED" || s === "RUNNING";

export interface UploadPolicy {
  enabled: boolean;
  kinds: { kind: string; max_mb: number }[];
  max_pages: number;
  retention_days: number;
}

/** Plain words, never colour alone (SC 1.4.1). */
export const DOC_STATUS: Record<DocumentRow["status"], string> = {
  UPLOADED: "Waiting to be checked",
  SCANNING: "Being checked",
  CLEAN: "Ready",
  REJECTED: "Not accepted",
  FAILED: "Could not be checked",
};

export const KIND_LABEL: Record<string, string> = { pdf: "PDF", docx: "Word", pptx: "PowerPoint", epub: "EPUB" };
export const isWaiting = (d: DocumentRow) => d.status === "UPLOADED" || d.status === "SCANNING" || auditActive(d.latest_audit?.status);

export function formatSize(bytes: number): string {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export interface FixPlan { title?: string; language?: string; alt?: Record<string, string>; heading_levels?: Record<string, number> }
export interface FixFinding { rule_id: string; title: string; severity: "critical" | "serious" | "moderate" | "minor" }
export interface FixResult {
  edits: number;
  before: { findings: number; by_severity: Record<string, number> };
  after: { findings: number; by_severity: Record<string, number> };
  resolved: FixFinding[];
  remaining: FixFinding[];
}
export interface FixRow {
  id: string;
  status: "DRAFT" | "QUEUED" | "RUNNING" | "READY" | "FAILED";
  plan: FixPlan;
  pages: number | null;
  result: Partial<FixResult>;
  result_document_id: string | null;
  error_code: string | null;
  error_detail: string | null;
}
export interface FixState {
  document: { id: string; filename: string; page_count: number | null };
  audit_id: string;
  structure: {
    has_structure: boolean;
    title: string;
    language: string;
    pages: number;
    figures: { id: string | null; editable: boolean; page: number | null; alt: string }[];
    headings: { id: string | null; editable: boolean; page: number | null; level: number; text: string }[];
    truncated: boolean;
  };
  fix: FixRow | null;
}
export const fixActive = (s?: FixRow["status"]) => s === "QUEUED" || s === "RUNNING";
export const LANGUAGES: { id: string; label: string }[] = [
  { id: "keep", label: "Leave as it is" }, { id: "en", label: "English" }, { id: "en-GB", label: "English (UK)" }, { id: "en-IN", label: "English (India)" },
  { id: "hi", label: "Hindi" }, { id: "ta", label: "Tamil" }, { id: "te", label: "Telugu" }, { id: "bn", label: "Bengali" }, { id: "mr", label: "Marathi" },
  { id: "gu", label: "Gujarati" }, { id: "kn", label: "Kannada" }, { id: "ml", label: "Malayalam" }, { id: "fr", label: "French" }, { id: "de", label: "German" },
  { id: "es", label: "Spanish" }, { id: "__other", label: "Another language (enter a code)" },
];
