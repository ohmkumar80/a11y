import type { Page } from "@playwright/test";

const BASE = {
  controls: { can_choose_region: true, can_enable_ai: false, can_set_retention: true, can_block_human_review: true, min_retention_days: 1 },
  chosen: { retention_days: null, storage_region: null, allow_human_review: true, ai_on_documents: false, ai_require_zero_retention: true, ai_regions: [] as string[] },
  effective: { retention_days: 30, retention_ceiling: 30, region: { id: "default", label: "Default region" }, allow_human_review: true, ai_on_documents: false, ai_require_zero_retention: true, ai_regions: [] as string[] },
  regions: [{ id: "default", label: "Default region" }, { id: "eu", label: "European Union (Frankfurt)" }],
  ai_region_options: ["eu", "in", "us"],
  documents: { stored: 4, by_region: { default: 3, eu: 1 } as Record<string, number> },
};

export const policyState = {
  data: structuredClone(BASE) as typeof BASE,
  saved: [] as Record<string, unknown>[],
  deleteCalls: [] as Record<string, unknown>[],
  saveError: null as null | { status: number; json: Record<string, unknown> },
  shortened: 0,
};

export function resetPolicy(over: Partial<typeof BASE.controls> = {}) {
  policyState.data = structuredClone(BASE);
  policyState.data.controls = { ...BASE.controls, ...over };
  policyState.saved = [];
  policyState.deleteCalls = [];
  policyState.saveError = null;
  policyState.shortened = 0;
}
resetPolicy();

export async function mockDataPolicy(page: Page) {
  await page.route(/\/api\/org\/data-policy\/delete-documents$/, (r) => {
    policyState.deleteCalls.push(r.request().postDataJSON());
    const n = policyState.data.documents.stored;
    policyState.data.documents = { stored: 0, by_region: {} };
    return r.fulfill({ json: { deleted: n } });
  });
  await page.route(/\/api\/org\/data-policy$/, (r) => {
    if (r.request().method() === "PUT") {
      if (policyState.saveError) return r.fulfill({ status: policyState.saveError.status, json: policyState.saveError.json });
      const b = r.request().postDataJSON() as typeof BASE.chosen;
      policyState.saved.push(b);
      policyState.data.chosen = b;
      policyState.data.effective = { ...policyState.data.effective, retention_days: b.retention_days ?? 30, allow_human_review: b.allow_human_review, ai_on_documents: b.ai_on_documents && policyState.data.controls.can_enable_ai };
      return r.fulfill({ json: { effective: policyState.data.effective, existing_files_shortened: policyState.shortened } });
    }
    return r.fulfill({ json: policyState.data });
  });
}
