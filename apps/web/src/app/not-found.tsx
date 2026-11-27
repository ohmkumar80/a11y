import type { Metadata } from "next";
import NextLink from "next/link";
import { Page } from "@/components/Page";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <Page title="Page not found" intro="The page you asked for does not exist or has moved.">
      <p><NextLink href="/" className="underline">Go to the home page</NextLink></p>
    </Page>
  );
}
