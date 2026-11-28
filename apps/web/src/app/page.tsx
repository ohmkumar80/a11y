import NextLink from "next/link";

const btnPrimary =
  "inline-flex min-h-13 items-center justify-center border-2 border-fg bg-accent px-7 py-2 text-lg font-bold text-accent-fg shadow-lift transition-[transform,box-shadow] hover:-translate-x-px hover:-translate-y-px hover:bg-accent-hover active:translate-x-0.5 active:translate-y-0.5 active:shadow-none";
const btnSecondary =
  "inline-flex min-h-13 items-center justify-center border-2 border-fg bg-bg px-7 py-2 text-lg font-bold text-fg shadow-lift transition-[transform,box-shadow] hover:-translate-x-px hover:-translate-y-px hover:bg-bg-inset active:translate-x-0.5 active:translate-y-0.5 active:shadow-none";

const parts = [
  { n: "1.1", title: "Several engines, one result", body: "We run more than one scan engine on every page and merge what they find. Each finding carries a confidence level, so you spend less time on duplicates and false alarms." },
  { n: "1.2", title: "Guidance in plain language", body: "Every rule explains the problem, who it affects and how to fix it, with a worked example and the WCAG success criterion it relates to." },
  { n: "1.3", title: "Fixes you can trust to review", body: "Suggested code fixes are re-scanned before you see them. You always decide whether to use one; nothing is changed on your site for you." },
  { n: "1.4", title: "The Fix Workbench", body: "See each issue outlined on a screenshot of the page, next to the guidance and the suggested fix, so developers can act without hunting." },
  { n: "1.5", title: "Reports that hold up", body: "Export an audit as a tagged PDF, Word or CSV, and start a VPAT. Reports are drafts until a named person signs them off, and exports unlock only after that." },
  { n: "1.6", title: "Built for teams and pipelines", body: "Roles for your organisation, multi-factor sign-in for administrators, a public API with keys, and webhooks that send results to your own tools." },
];

const steps = [
  { title: "Verify your domain", body: "Prove you own the site. We only scan domains you have verified." },
  { title: "Run a scan", body: "Start from a single URL or crawl the site. Progress and results are shown as they arrive." },
  { title: "Fix and report", body: "Work through findings in priority order, re-scan, then export a signed-off report." },
];

/** Drawn with CSS only. The text beside it says the same thing, so it is hidden from assistive technology. */
function Photo() {
  return (
    <div aria-hidden="true" className="grid size-20 shrink-0 place-items-center border-2 border-fg bg-bg-inset [background-image:repeating-linear-gradient(135deg,transparent_0_7px,var(--a11y-border-subtle)_7px_9px)]">
      <svg viewBox="0 0 24 24" className="size-8 text-fg" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="9" cy="9" r="2.2" /><path d="M3 18l5-5 4 4 3-3 6 6" /></svg>
    </div>
  );
}

function Heard({ label, code, said, bad }: { label: string; code: string; said: string; bad?: boolean }) {
  return (
    <div className="grid gap-4 p-5 sm:grid-cols-[auto_1fr] sm:items-center">
      <Photo />
      <div className="flex flex-col gap-2">
        <p className="a11y-kicker">{label}</p>
        <pre className="whitespace-pre-wrap text-sm [overflow-wrap:anywhere]"><code>{code}</code></pre>
        <p className={`border-l-4 pl-3 ${bad ? "border-danger text-danger" : "border-accent-2 text-accent-2"}`}>
          <span className="a11y-kicker !text-fg-muted">A screen reader says</span>
          <span className="block font-display text-xl font-semibold leading-snug">{said}</span>
        </p>
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <>
      <section aria-labelledby="hero-title" className="border-b-2 border-fg">
        <div className="mx-auto grid max-w-7xl gap-14 px-4 py-16 sm:px-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-center lg:py-24">
          <div className="flex flex-col gap-8">
            <p className="a11y-kicker a11y-rise">WCAG 2.2 AA · Web pages and documents</p>
            <h1 id="hero-title" tabIndex={-1} className="a11y-rise a11y-rise-2 text-[clamp(3rem,7.4vw,6.25rem)] font-semibold leading-[0.98]">
              Accessibility audits you can <span className="a11y-infocus whitespace-nowrap">act on</span>
            </h1>
            <p className="a11y-rise a11y-rise-2 max-w-xl text-xl text-fg-muted">
              Scan your website, understand every issue in plain language, review suggested fixes, and produce reports you can share
              with confidence.
            </p>
            <p className="a11y-rise a11y-rise-3 flex flex-wrap gap-4">
              <NextLink href="/signup" className={btnPrimary}>Start a 14-day trial</NextLink>
              <NextLink href="/login" className={btnSecondary}>Log in</NextLink>
            </p>
            <p className="a11y-rise a11y-rise-3 text-fg-muted">
              No card needed.{" "}
              <NextLink href="/accessibility" className="font-bold text-fg underline underline-offset-4 hover:text-accent">Read our accessibility statement</NextLink>.
            </p>
          </div>

          <figure className="a11y-rise a11y-rise-3 m-0">
            <div className="a11y-boxed shadow-lift">
              <p className="flex flex-wrap items-baseline gap-x-3 border-b-2 border-fg bg-bg-subtle px-5 py-3">
                <span className="a11y-kicker !text-danger">Serious</span>
                <span className="font-bold">WCAG 1.1.1 Non-text content (Level A)</span>
              </p>
              <h2 className="px-5 pt-5 text-2xl font-semibold">Image is missing a text alternative</h2>
              <Heard label="Before" code={'<img src="team.jpg">'} said="Graphic, team dot j p g" bad />
              <div className="border-t border-border-subtle" />
              <Heard label="After the suggested fix" code={'<img src="team.jpg" alt="The support team at their desks">'} said="Graphic, the support team at their desks" />
              <p className="flex items-center gap-2 border-t-2 border-fg bg-bg-subtle px-5 py-3 font-bold text-accent-2">
                <span aria-hidden="true">✓</span>
                Checked by re-scanning the fixed element
              </p>
            </div>
            <figcaption className="mt-4 text-sm text-fg-muted">An example finding. Every finding shows what people hear, and a fix you can review.</figcaption>
          </figure>
        </div>
      </section>

      <section aria-labelledby="features-title" className="mx-auto max-w-7xl px-4 py-24 sm:px-8">
        <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
          <div className="flex flex-col gap-4">
            <p className="a11y-kicker">§ 1 · The platform</p>
            <h2 id="features-title" className="text-4xl font-semibold sm:text-5xl">Everything between “is it accessible?” and “here is the proof”</h2>
          </div>
          <ol className="border-t-[3px] border-fg">
            {parts.map((p) => (
              <li key={p.n} className="grid gap-2 border-b border-border py-6 sm:grid-cols-[5rem_1fr] sm:gap-6 md:grid-cols-[5rem_minmax(0,0.9fr)_minmax(0,1.2fr)]">
                <span className="a11y-kicker pt-1.5">{p.n}</span>
                <h3 className="text-2xl font-semibold">{p.title}</h3>
                <p className="text-fg-muted sm:col-start-2 md:col-start-auto">{p.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section aria-labelledby="how-title" className="border-y-2 border-fg bg-bg-subtle">
        <div className="mx-auto max-w-7xl px-4 py-24 sm:px-8">
          <p className="a11y-kicker">§ 2 · How it works</p>
          <h2 id="how-title" className="mt-3 max-w-2xl text-4xl font-semibold sm:text-5xl">From first scan to signed report in three steps</h2>
          <ol className="mt-14 grid md:grid-cols-3 md:divide-x-2 md:divide-fg">
            {steps.map((s, i) => (
              <li key={s.title} className="flex flex-col gap-3 border-t-2 border-fg py-8 md:border-t-0 md:px-8 md:first:pl-0 md:last:pr-0">
                <span aria-hidden="true" className="font-display text-8xl font-semibold leading-none text-accent">{i + 1}</span>
                <h3 className="text-2xl font-semibold">
                  <span className="a11y-sr-only">Step {i + 1}: </span>
                  {s.title}
                </h3>
                <p className="max-w-sm text-fg-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section aria-labelledby="honest-title" className="a11y-ink">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-24 sm:px-8 lg:grid-cols-[1.2fr_1fr] lg:items-end">
          <h2 id="honest-title" className="text-[clamp(2.5rem,5.5vw,4.5rem)] font-semibold leading-[1.02]">Automated testing is a start, not a <span className="a11y-infocus">verdict</span></h2>
          <div className="flex flex-col gap-4 text-lg text-inverse-muted">
            <p>
              No scanner can prove a site is fully accessible, and we will not tell you otherwise. Every report we produce is marked as
              a draft until a person has reviewed it and signed it off.
            </p>
            <p>That is the difference between a report you can share with a regulator or a customer and one you cannot.</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="cta-title" className="border-b-2 border-fg">
        <div className="mx-auto flex max-w-7xl flex-col items-start gap-7 px-4 py-20 sm:px-8 sm:py-24">
          <h2 id="cta-title" className="max-w-4xl text-4xl font-semibold sm:text-6xl">See what your site looks like to everyone who uses it</h2>
          <p className="max-w-xl text-xl text-fg-muted">Start a 14-day trial and run your first scan in minutes.</p>
          <p className="flex flex-wrap gap-4">
            <NextLink href="/signup" className={btnPrimary}>Start a 14-day trial</NextLink>
            <NextLink href="/developers" className={btnSecondary}>Explore the API</NextLink>
          </p>
        </div>
      </section>
    </>
  );
}
