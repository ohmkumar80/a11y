import NextLink from "next/link";
import { Page } from "@/components/Page";

export default function Home() {
  return (
    <Page title="Accessibility audits you can act on" intro="Scan, fix and document accessibility across websites, documents, media and mobile apps.">
      <p className="max-w-prose">
        We combine several scan engines, explain each issue in plain language and give you fixes you can review before using. Reports
        are drafts until a person signs them off: automated testing cannot prove full conformance on its own.
      </p>
      <p className="flex flex-wrap gap-4">
        <NextLink href="/signup" className="inline-flex min-h-11 items-center rounded-md border-2 border-transparent bg-accent px-4 py-2 font-semibold text-accent-fg hover:bg-accent-hover">
          Start a 14-day trial
        </NextLink>
        <NextLink href="/login" className="inline-flex min-h-11 items-center rounded-md border-2 border-border px-4 py-2 font-semibold">
          Log in
        </NextLink>
      </p>
    </Page>
  );
}
