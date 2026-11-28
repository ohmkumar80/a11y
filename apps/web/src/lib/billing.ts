export type SubStatus = "TRIALING" | "ACTIVE" | "PAST_DUE" | "LOCKED_READ_ONLY";

export interface Subscription {
  plan: { id: string; name: string };
  status: SubStatus;
  trial_ends_at: string | null;
  seats: { used: number; limit: number | null };
  quotas: Array<{ feature: string; enabled: boolean; used: number; limit: number | null; custom?: boolean }>;
  coupon: { code: string; type: "PERCENTAGE" | "FIXED_INR"; value: number } | null;
}

export const STATUS_LABEL: Record<SubStatus, string> = {
  TRIALING: "Trial",
  ACTIVE: "Active",
  PAST_DUE: "Payment overdue",
  LOCKED_READ_ONLY: "Read-only (trial ended)",
};

const FEATURE_LABEL: Record<string, string> = {
  seats: "Seats",
  urls_monthly: "Website scans this month",
  ai_code_fixes_monthly: "AI code fixes this month",
  pages_per_scan: "Pages per scan",
};
/** Unknown feature keys (admins can add new ones) fall back to a readable form of the key. */
export const featureLabel = (k: string) => FEATURE_LABEL[k] ?? k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function discountText(c: { type: string; value: number }) {
  return c.type === "PERCENTAGE" ? `${c.value}% off` : `₹${(c.value / 100).toLocaleString("en-IN")} off`;
}

export const formatDate = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { dateStyle: "long" });
export const daysLeft = (iso: string) => Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000));
