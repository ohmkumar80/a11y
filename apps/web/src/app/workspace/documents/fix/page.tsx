"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { StatusMessage } from "@a11y/ui";
import { FixEditor } from "@/components/FixEditor";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { download, get } from "@/lib/api";
import type { FixState } from "@/lib/documents";

function Content() {
  const doc = useSearchParams().get("doc");
  if (!doc) return <StatusMessage>This page needs a document. Open it from your documents.</StatusMessage>;
  return (
    <FixEditor
      variant="customer"
      base={`/documents/${doc}/fix`}
      load={() => get<FixState>(`/documents/${doc}/fix`)}
      downloadCopy={(fix) => void download(`/documents/${fix.result_document_id}/download`)}
    />
  );
}

export default function FixPage() {
  return (
    <RequireAuth>
      {() => (
        <Page title="Fix a document" intro="Describe images, set the title and language, and correct heading levels. We build a fixed copy and check it again.">
          <p><NextLink href="/workspace/documents" className="underline">Back to your documents</NextLink></p>
          <Suspense><Content /></Suspense>
        </Page>
      )}
    </RequireAuth>
  );
}
