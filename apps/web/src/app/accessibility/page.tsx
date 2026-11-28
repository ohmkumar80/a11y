import { Page } from "@/components/Page";

export default function AccessibilityStatementPage() {
  return (
    <Page title="Accessibility statement" intro="Draft. To be reviewed by our accessibility lead before the first paid customer.">
      <div className="flex max-w-prose flex-col gap-4">
        <section aria-labelledby="target"><h2 id="target" className="text-xl font-bold">Our target</h2>
          <p>We aim for WCAG 2.2 Level AA on every screen, email and file we generate. This also supports EN 301 549 and Section 508.</p></section>
        <section aria-labelledby="status"><h2 id="status" className="text-xl font-bold">Current status</h2>
          <p>We have not yet completed an independent audit. Automated checks run on every change. Manual screen reader testing is planned for each release.</p></section>
        <section aria-labelledby="known"><h2 id="known" className="text-xl font-bold">Known issues</h2>
          <p>None recorded yet.</p></section>
        <section aria-labelledby="feedback"><h2 id="feedback" className="text-xl font-bold">Feedback</h2>
          <p>Email <a className="underline" href="mailto:accessibility@a11y.example">accessibility@a11y.example</a>. We reply within two working days.</p></section>
      </div>
    </Page>
  );
}
