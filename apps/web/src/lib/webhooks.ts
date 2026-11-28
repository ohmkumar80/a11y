export interface Endpoint {
  id: string; url: string; description: string; events: string[]; enabled: boolean; disabled_reason: string | null; secret_hint: string;
  consecutive_failures: number; last_success_at: string | null; created_at: string;
  last_delivery: { status: string; at: string; response_status: number | null; error: string | null } | null;
}
export interface EndpointList {
  entitled: boolean; switched_off: boolean; upgrade_url: string; max_endpoints: number; events: Record<string, string>; endpoints: Endpoint[];
}
export interface NewEndpoint extends Endpoint { secret: string; notice: string }
export interface Delivery {
  id: string; event_id: string; event_type: string; status: "PENDING" | "SENDING" | "SENT" | "ABANDONED"; attempts: number;
  response_status: number | null; error: string | null; created_at: string; delivered_at: string | null; next_attempt_at: string | null;
}
export const DELIVERY_STATE: Record<string, string> = { PENDING: "Will retry", SENDING: "Sending", SENT: "Delivered", ABANDONED: "Gave up" };
