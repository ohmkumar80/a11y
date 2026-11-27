"use client";

import { Button, Dialog, DialogTrigger } from "@a11y/ui";
import { CONFIDENCE_LABEL, KIND_LABEL, SEVERITY_LABEL, type Finding } from "@/lib/scans";

export function FindingDetails({ f }: { f: Finding }) {
  return (
    <DialogTrigger>
      <Button variant="secondary" className="whitespace-nowrap">Details<span className="a11y-sr-only"> for {f.title} on {f.element.tag}</span></Button>
      <Dialog title={f.title}>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
          <dt className="font-semibold">Type</dt><dd>{KIND_LABEL[f.kind]}, {SEVERITY_LABEL[f.severity].toLowerCase()}</dd>
          <dt className="font-semibold">Criteria</dt><dd>{f.criteria.length ? f.criteria.map((c) => `${c.clause} ${c.name} (level ${c.level})`).join("; ") : "Best practice (not a WCAG requirement)"}</dd>
          <dt className="font-semibold">Confidence</dt><dd>{CONFIDENCE_LABEL[f.confidence]} ({f.agreement}: {f.engines.join(", ")})</dd>
          <dt className="font-semibold">Page</dt><dd className="[overflow-wrap:anywhere]">{f.page.url}</dd>
          <dt className="font-semibold">Element</dt><dd><code className="[overflow-wrap:anywhere]">{f.element.css}</code></dd>
        </dl>
        {f.message && <p>{f.message}</p>}
        <p className="font-semibold">HTML of the element</p>
        <pre className="overflow-x-auto rounded border border-border p-2"><code>{f.element.html}</code></pre>
        {f.help_url && <p><a href={f.help_url} className="underline" target="_blank" rel="noreferrer">Read more about this rule<span className="a11y-sr-only"> (opens in a new tab)</span></a></p>}
      </Dialog>
    </DialogTrigger>
  );
}
