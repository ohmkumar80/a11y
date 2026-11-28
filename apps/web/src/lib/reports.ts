export type ReportKind = "audit_pdf" | "audit_docx" | "audit_csv" | "vpat_pdf" | "vpat_docx";
export interface Report {
  id: string; scan_id: string; kind: ReportKind; standard: string; status: "QUEUED" | "RUNNING" | "READY" | "FAILED";
  error_detail: string | null; size_bytes: number | null; created_at: string; vpat_id: string | null;
  validation: { gate?: string; passed?: boolean };
}
export const KIND_LABEL: Record<ReportKind, string> = {
  audit_pdf: "Audit report (PDF)", audit_docx: "Audit report (Word)", audit_csv: "All findings (CSV)", vpat_pdf: "VPAT (PDF)", vpat_docx: "VPAT (Word)",
};
export const REPORT_STATUS: Record<Report["status"], string> = { QUEUED: "Waiting to start", RUNNING: "Being prepared", READY: "Ready", FAILED: "Failed" };
export const formatSize = (n: number | null) => (n === null ? "" : n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

export type Conformance = "Supports" | "Partially Supports" | "Does Not Support" | "Not Applicable" | "Not Evaluated";
export interface VpatCriterion {
  id: string; name: string; level: "A" | "AA" | "AAA"; clause: string; conformance: Conformance; remarks: string; source: "automated" | "manual" | "default";
  failures: number; failing_pages: number; scanned_pages: number; review_items: number; automated_check_exists: boolean;
}
export interface Vpat {
  id: string; scan_id: string; standard: string; edition: string; status: "DRAFT" | "SIGNED_OFF"; product: Record<string, string>; criteria: VpatCriterion[];
  levels: Conformance[]; mapping_review: string; signoff: { name: string; role: string; signed_at: string } | null; not_evaluated: number; total: number;
  problems: string[]; signoff_text: string;
}
