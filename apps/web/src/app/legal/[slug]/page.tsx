"use client";

import NextLink from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Markdown } from "@/components/admin/Markdown";
import { Page } from "@/components/Page";
import { get } from "@/lib/api";
import { formatDate } from "@/lib/billing";

interface LegalDoc { slug: string; title: string; version: string; effective_date: string | null; body: string }
const FALLBACK: Record<string, string> = {
  terms: "Terms of service", privacy: "Privacy policy", cookies: "Cookie policy", dpa: "Data processing agreement",
  "acceptable-use": "Acceptable use policy", refunds: "Refund policy",
};

/** A legal page exactly as an administrator published it. Open to everyone: nobody should have to sign in to read terms. */
export default function LegalPage() {
  const { slug } = useParams<{ slug: string }>();
  const [doc, setDoc] = useState<LegalDoc | null | undefined>(undefined);
  useEffect(() => { void get<LegalDoc>(`/legal/${encodeURIComponent(slug)}`).then((r) => setDoc(r.ok ? r.data : null)); }, [slug]);

  return (
    <Page title={doc?.title ?? FALLBACK[slug] ?? "Legal"} intro={doc ? [doc.version && `Version ${doc.version}`, doc.effective_date && `in force from ${formatDate(doc.effective_date)}`].filter(Boolean).join(", ") : undefined}>
      {doc === undefined && <p role="status">Loading.</p>}
      {doc === null && (
        <p>This page has not been published yet. If you need it, <NextLink href="/help" className="underline">contact us</NextLink>.</p>
      )}
      {doc && <Markdown source={doc.body} base={2} />}
    </Page>
  );
}
