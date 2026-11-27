export type FixStatus = "PENDING" | "RUNNING" | "READY" | "NEEDS_REVIEW" | "FAILED";
export interface FixCheck { name: string; passed: boolean; detail: string }
export interface Fix {
  id: string; finding_id: string; rule: string; status: FixStatus; rung: "recipe" | "light" | null;
  original_html: string; fixed_html: string | null; explanation: string; notes: string[]; checks: FixCheck[];
  reason: string | null; detail: string | null; model_id: string | null; attempts: number; from_cache: boolean;
}
export const RUNG_LABEL: Record<string, string> = {
  recipe: "Ready-made fix for this pattern",
  light: "Suggested by an AI model",
};
