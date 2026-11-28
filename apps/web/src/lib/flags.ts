"use client";

import { useApi } from "./useApi";

export interface Flags { public_api: boolean; webhooks: boolean; vpat: boolean; crawl_scans: boolean; notification_center: boolean; documents: boolean; human_review: boolean }

/** Which features an administrator has switched on for this organisation. While loading, everything counts as on, so a
 *  feature never flickers away and back; the server enforces the real answer either way. */
export function useFlags(): Flags {
  const { data } = useApi<Flags>("/org/flags");
  return data ?? { public_api: true, webhooks: true, vpat: true, crawl_scans: true, notification_center: true, documents: true, human_review: true };
}
