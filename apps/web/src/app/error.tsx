"use client";

import { Button } from "@a11y/ui";
import { Page } from "@/components/Page";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <Page title="Something went wrong" intro="We could not show this page. Try again, and contact us if it keeps happening.">
      <div role="alert" className="sr-only">An error occurred.</div>
      <div><Button onPress={reset}>Try again</Button></div>
    </Page>
  );
}
