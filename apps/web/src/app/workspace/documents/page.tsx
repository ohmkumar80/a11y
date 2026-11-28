"use client";

import NextLink from "next/link";
import { useState } from "react";
import { StatusMessage } from "@a11y/ui";
import { DocumentUpload } from "@/components/DocumentUpload";
import { DocumentsList } from "@/components/DocumentsList";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { useFlags } from "@/lib/flags";

function Content() {
  const flags = useFlags();
  const [version, setVersion] = useState(0);
  if (!flags.documents) {
    return <StatusMessage>Document checks are switched off for your account at the moment. <NextLink href="/workspace" className="underline">Back to the workspace</NextLink>.</StatusMessage>;
  }
  return (
    <>
      <DocumentUpload onUploaded={() => setVersion((v) => v + 1)} />
      <DocumentsList refreshKey={version} />
    </>
  );
}

export default function DocumentsPage() {
  return (
    <RequireAuth>
      {(user) => (
        <Page title="Documents" intro="Upload PDF, Word, PowerPoint and EPUB files. Every file is scanned for viruses and checked before anything else happens to it, and is stored encrypted.">
          {user.role === "SUPER_ADMIN" || user.role === "REVIEWER" ? <StatusMessage>Platform staff do not have documents of their own. Administrators use the Documents tab in the admin area; reviewers use the review queue.</StatusMessage> : <Content />}
        </Page>
      )}
    </RequireAuth>
  );
}
