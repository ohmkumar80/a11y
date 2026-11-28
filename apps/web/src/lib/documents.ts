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
}

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
export const isWaiting = (s: DocumentRow["status"]) => s === "UPLOADED" || s === "SCANNING";

export function formatSize(bytes: number): string {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
