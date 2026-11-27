"use client";

import { useCallback, useEffect, useState } from "react";
import { get, type Problem } from "./api";

/** Load a GET endpoint once on mount; `reload()` refetches. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Problem | null>(null);
  const reload = useCallback(async () => {
    if (path === null) return;
    const r = await get<T>(path);
    if (r.ok) { setData(r.data); setError(null); } else setError(r.problem);
  }, [path]);
  useEffect(() => {
    setData(null);
    void reload();
  }, [reload]);
  return { data, error, reload };
}
