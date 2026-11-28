import { Page } from "@/components/Page";

export default function HelpPage() {
  return (
    <Page title="Help and contact" intro="We reply within two working days.">
      <section aria-labelledby="contact" className="flex max-w-prose flex-col gap-2">
        <h2 id="contact" className="text-xl font-bold">Contact support</h2>
        <p>Email <a className="underline" href="mailto:support@a11y.example">support@a11y.example</a>. Tell us the page you were on and what you expected.</p>
      </section>
      <section aria-labelledby="a11y-feedback" className="flex max-w-prose flex-col gap-2">
        <h2 id="a11y-feedback" className="text-xl font-bold">Report an accessibility problem</h2>
        <p>Email <a className="underline" href="mailto:accessibility@a11y.example">accessibility@a11y.example</a>. We acknowledge reports within two working days.</p>
      </section>
    </Page>
  );
}
