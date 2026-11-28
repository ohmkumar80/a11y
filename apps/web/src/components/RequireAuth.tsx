"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import type { User } from "@/lib/api";
import { useAuth } from "./AuthProvider";
import { Page } from "./Page";

/** Client-side gate. The API enforces the same roles on every endpoint; this is only UX. */
export function RequireAuth({ requiredRole, children }: { requiredRole?: User["role"] | User["role"][]; children: (user: User) => ReactNode }) {
  const { user } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (user === null) router.replace("/login");
  }, [user, router]);

  if (user === undefined || user === null) {
    return <Page title="Loading"><p role="status">Checking your session. Please wait.</p></Page>;
  }
  if (requiredRole && ![requiredRole].flat().includes(user.role)) {
    return <Page title="You do not have access" intro="Your role cannot open this page. Ask an administrator in your organisation if you need access." />;
  }
  return <>{children(user)}</>;
}
