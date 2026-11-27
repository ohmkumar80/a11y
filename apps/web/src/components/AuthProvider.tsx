"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { post, refreshSession, setAccessToken, type Problem, type Session, type User } from "@/lib/api";

interface AuthState {
  /** undefined while the first refresh is in flight; null when signed out */
  user: User | null | undefined;
  login: (email: string, password: string) => Promise<Problem | null>;
  logout: () => Promise<void>;
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
        const r = await post<Session>("/auth/login", { email, password });
        if (!r.ok) return r.problem;
        adopt(r.data);
        return null;
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
