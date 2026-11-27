import type { Metadata } from "next";

const TITLES: Record<string, string> = {
  terms: "Terms of service", privacy: "Privacy policy", cookies: "Cookie policy", dpa: "Data processing agreement",
  "acceptable-use": "Acceptable use policy", refunds: "Refund policy",
};

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  return { title: TITLES[slug] ?? "Legal" };
}
export default function Layout({ children }: { children: React.ReactNode }) { return children; }
