"use client";

import NextLink from "next/link";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";

const navLink = "inline-flex min-h-11 items-center px-3 underline-offset-4 hover:underline";

/** Footer links to whichever legal pages are published. With none published there is nothing to show, so nothing is. */
export function LegalLinks() {
  const [pages, setPages] = useState<Array<{ slug: string; title: string }>>([]);
  useEffect(() => { void get<Array<{ slug: string; title: string }>>("/legal").then((r) => r.ok && setPages(r.data)); }, []);
  return <>{pages.map((p) => <NextLink key={p.slug} href={`/legal/${p.slug}`} className={navLink}>{p.title}</NextLink>)}</>;
}
