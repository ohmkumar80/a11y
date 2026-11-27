export interface Problem {
  detail: string;
  code?: string;
  field?: string;
  /** Whole error body, for structured errors (seat limit, limit below usage ...). */
  body?: Record<string, unknown>;
}

export type Result<T> = { ok: true; data: T } | { ok: false; status: number; problem: Problem };

export interface User {
  id: string;
  email: string;
  role: "SUPER_ADMIN" | "COMPANY_ADMIN" | "STANDARD_USER";
  organization_id: string;
  organization_name: string;
  mfa_enabled?: boolean;
}

/** Returned instead of a session when a second step is needed. */
export interface MfaChallenge {
  mfa: "verify" | "enroll";
  mfa_token: string;
  expires_in: number;
  issuer: string;
}
export interface EnrolInfo { key: string; otpauth_uri: string; issuer: string; account: string }

export interface Session {
  access_token: string;
  expires_in: number;
  user: User;
}

let accessToken: string | null = null;
export function setAccessToken(t: string | null) {
  accessToken = t;
}

async function raw<T>(path: string, init: RequestInit & { json?: unknown }): Promise<Result<T>> {
  const headers = new Headers(init.headers);
  if (init.json !== undefined) headers.set("content-type", "application/json");
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers,
      credentials: "same-origin",
      body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
    });
  } catch {
    return { ok: false, status: 0, problem: { detail: "We could not reach the server. Check your connection and try again." } };
  }
  if (res.ok) return { ok: true, data: (res.status === 204 ? undefined : await res.json().catch(() => undefined)) as T };
  const body = await res.json().catch(() => ({}));
  const detail = typeof body?.detail === "string" ? body.detail : "Something went wrong. Try again.";
  return { ok: false, status: res.status, problem: { detail, code: body?.code, field: body?.field ?? undefined, body } };
}

export const post = <T = void>(path: string, json?: unknown) => raw<T>(path, { method: "POST", json });
export const get = <T>(path: string) => raw<T>(path, { method: "GET" });
export const put = <T = void>(path: string, json?: unknown) => raw<T>(path, { method: "PUT", json });
export const patch = <T = void>(path: string, json?: unknown) => raw<T>(path, { method: "PATCH", json });

/**
 * Refresh is single-flight within the tab AND across tabs (Web Locks). Refresh tokens rotate and
 * a replayed token revokes the whole session family, so two concurrent refreshes (React strict
 * mode, two tabs) would otherwise log the user out.
 */
let inflight: Promise<Result<Session>> | null = null;
export function refreshSession(): Promise<Result<Session>> {
  inflight ??= (async () => {
    const run = () => post<Session>("/auth/refresh");
    try {
      return navigator.locks ? await navigator.locks.request("a11y-refresh", run) : await run();
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Download a file from an authenticated endpoint. A plain link cannot send the bearer token, so fetch, then save the blob. */
export async function download(path: string): Promise<{ ok: true } | { ok: false; problem: Problem }> {
  const headers = new Headers();
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { headers, credentials: "same-origin" });
  } catch {
    return { ok: false, problem: { detail: "We could not reach the server. Check your connection and try again." } };
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return { ok: false, problem: { detail: typeof body?.detail === "string" ? body.detail : "The download failed. Try again.", code: body?.code } };
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "report";
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return { ok: true };
}

/** Fetch a private image (the API needs our token, which an <img src> cannot send) and return a local URL for it. */
export async function getBlobUrl(path: string): Promise<{ ok: true; url: string } | { ok: false; problem: Problem }> {
  const headers = new Headers();
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { headers, credentials: "same-origin" });
  } catch {
    return { ok: false, problem: { detail: "We could not reach the server. Check your connection and try again." } };
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return { ok: false, problem: { detail: typeof body?.detail === "string" ? body.detail : "The picture could not be loaded." } };
  }
  return { ok: true, url: URL.createObjectURL(await res.blob()) };
}
