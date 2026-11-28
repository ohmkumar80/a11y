import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { SkipLink, ToastProvider } from "@a11y/ui";
import { AuthProvider } from "@/components/AuthProvider";
import { MainContainer } from "@/components/MainContainer";
import { RouteAnnouncer } from "@/components/RouteAnnouncer";
import { SiteFooter, SiteHeader } from "@/components/SiteHeader";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "a11y: accessibility audits", template: "%s | a11y" },
  description: "Find, fix and prove accessibility compliance across web, documents, media and mobile.",
};

// Never disable zoom (SC 1.4.4 / 1.4.10).
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col">
        <SkipLink />
        <AuthProvider>
          <SiteHeader />
          <MainContainer>{children}</MainContainer>
          <SiteFooter />
          <RouteAnnouncer />
          <ToastProvider />
        </AuthProvider>
      </body>
    </html>
  );
}
