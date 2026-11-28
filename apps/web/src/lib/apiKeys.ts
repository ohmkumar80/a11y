export interface ApiKeyRow {
  id: string; name: string; hint: string; scopes: string[]; state: "active" | "expired" | "revoked";
  created_at: string; expires_at: string | null; last_used_at: string | null; revoked_at: string | null;
}
export interface ApiKeyList {
  entitled: boolean; upgrade_url: string; max_keys: number; max_lifetime_days: number | null;
  scopes: Record<string, string>; keys: ApiKeyRow[];
}
export interface NewKey extends ApiKeyRow { key: string; notice: string }
