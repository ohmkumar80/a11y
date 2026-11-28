import NextLink from "next/link";
import { FeatureIcon, type IconName } from "@/components/FeatureIcon";

const features: Array<{ icon: IconName; title: string; body: string }> = [
  {
    icon: "layers",
    title: "Several engines, one result",
    body: "We run more than one scan engine on every page and merge what they find. Each finding carries a confidence level, so you spend less time on duplicates and false alarms.",
  },
  {
    icon: "book",
    title: "Guidance in plain language",
    body: "Every rule explains the problem, who it affects and how to fix it, with a worked example and the WCAG success criterion it relates to.",
  },
  {
    icon: "shield",
    title: "Fixes you can trust to review",
    body: "Suggested code fixes are re-scanned before you see them. You always decide whether to use one; nothing is changed on your site for you.",
  },
  {
    icon: "monitor",
    title: "The Fix Workbench",
    body: "See each issue outlined on a screenshot of the page, next to the guidance and the suggested fix, so developers can act without hunting.",
  },
  {
    icon: "file",
    title: "Reports that hold up",
    body: "Export an audit as a tagged PDF, Word or CSV, and start a VPAT. Reports are drafts until a named person signs them off, and exports unlock only after that.",
  },
  {
    icon: "code",
    title: "Built for teams and pipelines",
    body: "Roles for your organisation, multi-factor sign-in for administrators, a public API with keys, and webhooks that send results to your own tools.",
  },
];

const steps = [
  { title: "Verify your domain", body: "Prove you own the site. We only scan domains you have verified." },
  { title: "Run a scan", body: "Start from a single URL or crawl the site. Progress and results are shown as they arrive." },
  { title: "Fix and report", body: "Work through findings in priority order, re-scan, then export a signed-off report." },
];

const ctaPrimary =
  "inline-flex min-h-12 items-center justify-center rounded-lg border-2 border-transparent bg-inverse-fg px-6 py-2 text-lg font-bold text-inverse-bg shadow-sm hover:bg-inverse-muted";
const ctaSecondary =
  "inline-flex min-h-12 items-center justify-center rounded-lg border-2 border-inverse-border px-6 py-2 text-lg font-semibold text-inverse-fg hover:bg-white/10";

export default function Home() {
  return (
    <>
      <section aria-labelledby="hero-title" className="a11y-hero text-inverse-fg">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 sm:py-20 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="flex flex-col gap-6">
            <p className="text-sm font-bold uppercase tracking-widest text-inverse-accent">Website accessibility audits</p>
            <h1 id="hero-title" tabIndex={-1} className="text-4xl font-extrabold sm:text-5xl lg:text-6xl">
              Accessibility audits you can act on
            </h1>
            <p className="max-w-xl text-lg text-inverse-muted sm:text-xl">
              Scan your website, understand every issue in plain language, review suggested fixes, and produce reports you can share
              with confidence.
            </p>
            <p className="flex flex-wrap gap-3">
              <NextLink href="/signup" className={ctaPrimary}>Start a 14-day trial</NextLink>
              <NextLink href="/login" className={ctaSecondary}>Log in</NextLink>
            </p>
            <p className="text-sm text-inverse-muted">
              Built to WCAG 2.2 AA.{" "}
              <NextLink href="/accessibility" className="font-semibold text-inverse-accent underline underline-offset-4 hover:text-inverse-fg">
                Read our accessibility statement
              </NextLink>
              .
            </p>
          </div>

          <figure className="m-0">
            <div className="rounded-2xl border-2 border-inverse-border bg-bg p-5 text-fg shadow-xl">
              <p className="flex flex-wrap items-center gap-2 text-sm font-bold">
                <span className="rounded-full border-2 border-danger bg-danger-bg px-2.5 py-0.5 text-danger-fg">Serious</span>
                <span className="text-fg-muted">WCAG 1.1.1 Non-text content (Level A)</span>
              </p>
              <p className="mt-3 text-lg font-bold">Image is missing a text alternative</p>
              <p className="mt-1 text-fg-muted">A screen reader user hears the file name instead of what the image shows.</p>
              <p className="mt-4 text-sm font-bold text-fg-muted">Suggested fix</p>
              <pre className="mt-1 whitespace-pre-wrap rounded-xl bg-bg-inset p-3 font-mono text-sm [overflow-wrap:anywhere]">
                <code>{'<img src="team.jpg" alt="The support team at their desks">'}</code>
              </pre>
              <p className="mt-3 flex items-center gap-2 text-sm font-semibold text-success-fg">
                <span aria-hidden="true" className="grid size-5 place-items-center rounded-full bg-success text-xs text-bg">✓</span>
                Checked by re-scanning the fixed element
              </p>
            </div>
            <figcaption className="mt-3 text-sm text-inverse-muted">An example finding with a reviewable fix.</figcaption>
          </figure>
        </div>
      </section>

      <section aria-labelledby="features-title" className="mx-auto max-w-6xl px-4 py-16">
        <div className="flex max-w-2xl flex-col gap-3">
          <h2 id="features-title" className="text-3xl font-extrabold sm:text-4xl">Everything between “is it accessible?” and “here is the proof”</h2>
          <p className="text-lg text-fg-muted">One place to find problems, fix them and document the result.</p>
        </div>
        <ul className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <li key={f.title} className="flex flex-col gap-3 rounded-2xl border-2 border-border-subtle bg-bg p-6 shadow-sm">
              <FeatureIcon name={f.icon} />
              <h3 className="text-xl font-bold">{f.title}</h3>
              <p className="text-fg-muted">{f.body}</p>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="how-title" className="border-y-2 border-border-subtle bg-bg-subtle">
        <div className="mx-auto max-w-6xl px-4 py-16">
          <h2 id="how-title" className="text-3xl font-extrabold sm:text-4xl">How it works</h2>
          <ol className="mt-10 grid gap-5 md:grid-cols-3">
            {steps.map((s, i) => (
              <li key={s.title} className="flex gap-4 rounded-2xl border-2 border-border-subtle bg-bg p-6">
                <span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-lg font-extrabold text-accent-fg">
                  {i + 1}
                </span>
                <div className="flex flex-col gap-1">
                  <h3 className="text-xl font-bold">
                    <span className="a11y-sr-only">Step {i + 1}: </span>
                    {s.title}
                  </h3>
                  <p className="text-fg-muted">{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section aria-labelledby="honest-title" className="mx-auto max-w-6xl px-4 py-16">
        <div className="grid gap-8 rounded-3xl border-2 border-accent bg-accent-subtle p-8 sm:p-12 lg:grid-cols-[1fr_1.2fr] lg:items-center">
          <h2 id="honest-title" className="text-3xl font-extrabold sm:text-4xl">Automated testing is a start, not a verdict</h2>
          <div className="flex flex-col gap-3 text-lg">
            <p>
              No scanner can prove a site is fully accessible, and we will not tell you otherwise. Every report we produce is marked as
              a draft until a person has reviewed it and signed it off.
            </p>
            <p>That is the difference between a report you can share with a regulator or a customer and one you cannot.</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="cta-title" className="a11y-hero text-inverse-fg">
        <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-4 py-14 sm:py-16">
          <h2 id="cta-title" className="max-w-2xl text-3xl font-extrabold sm:text-4xl">See what your site looks like to everyone who uses it</h2>
          <p className="max-w-xl text-lg text-inverse-muted">Start a 14-day trial and run your first scan in minutes.</p>
          <p className="flex flex-wrap gap-3">
            <NextLink href="/signup" className={ctaPrimary}>Start a 14-day trial</NextLink>
            <NextLink href="/developers" className={ctaSecondary}>Explore the API</NextLink>
          </p>
        </div>
      </section>
    </>
  );
}
