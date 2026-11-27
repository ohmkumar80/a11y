"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { post, refreshSession, setAccessToken, type EnrolInfo, type MfaChallenge, type Problem, type Session, type User } from "@/lib/api";

export type LoginResult = { kind: "ok" } | { kind: "problem"; problem: Problem } | { kind: "mfa"; challenge: MfaChallenge };

interface AuthState {
  /** undefined while the first refresh is in flight; null when signed out */
  user: User | null | undefined;
  login: (email: string, password: string) => Promise<LoginResult>;
  logout: () => Promise<void>;
  /** Second step of signing in (the mfa token proves the password step succeeded). */
  verifyMfa: (token: string, input: { code?: string; recovery_code?: string }) => Promise<Problem | null>;
  enrolStart: (token: string) => Promise<{ info: EnrolInfo } | { problem: Problem }>;
  /** Confirms the code and signs in; returns the one-time recovery codes. */
  enrolConfirm: (token: string, code: string) => Promise<{ codes: string[] } | { problem: Problem }>;
  /** Replace the signed-in user's cached profile (e.g. after turning MFA on or off). */
  patchUser: (p: Partial<User>) => void;
}

const Ctx = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const adopt = useCallback((s: Session | null) => {
    clearTimeout(timer.current);
    setAccessToken(s?.access_token ?? null);
    setUser(s?.user ?? null);
    if (s) {
      // Silent refresh a minute before the access token expires.
      timer.current = setTimeout(async () => {
        const r = await refreshSession();
        adopt(r.ok ? r.data : null);
      }, Math.max(10, s.expires_in - 60) * 1000);
    }
  }, []);

  useEffect(() => {
    let live = true;
    refreshSession().then((r) => live && adopt(r.ok ? r.data : null));
    return () => {
      live = false;
      clearTimeout(timer.current);
    };
  }, [adopt]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      async login(email, password) {
        const r = await post<Session | MfaChallenge>("/auth/login", { email, password });
        if (!r.ok) return { kind: "problem", problem: r.problem };
        if ("mfa" in r.data) return { kind: "mfa", challenge: r.data };
        adopt(r.data);
        return { kind: "ok" };
      },
      async verifyMfa(token, input) {
        const r = await post<Session>("/auth/mfa/verify", { mfa_token: token, ...input });
        if (!r.ok) return r.problem;
        adopt(r.data);
        return null;
      },
      async enrolStart(token) {
        const r = await post<EnrolInfo>("/auth/mfa/enroll/start", { mfa_token: token });
        return r.ok ? { info: r.data } : { problem: r.problem };
      },
      async enrolConfirm(token, code) {
        const r = await post<Session & { recovery_codes: string[] }>("/auth/mfa/enroll/confirm", { mfa_token: token, code });
        if (!r.ok) return { problem: r.problem };
        adopt(r.data);
        return { codes: r.data.recovery_codes };
      },
      patchUser(p) {
        setUser((u) => (u ? { ...u, ...p } : u));
      },
      async logout() {
        await post("/auth/logout");
        adopt(null);
      },
    }),
    [user, adopt],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
