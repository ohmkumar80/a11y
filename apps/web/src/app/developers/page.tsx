"use client";

import { Button, StatusMessage } from "@a11y/ui";
import { Fragment, useEffect, useState } from "react";
import { Page } from "@/components/Page";
import { curl, exampleOf, fields, inline, refName, resolve, type Operation, type Spec } from "@/lib/openapi";

const METHOD_ORDER = ["get", "post", "put", "patch", "delete"];
const SAMPLE = `import hmac, hashlib, time

def is_valid(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    t = int(parts["t"])
    if abs(time.time() - t) > tolerance:          # reject old requests (replay protection)
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"t={t},v1={expected}", header)`;

function Text({ text }: { text: string }) {
  return (
    <>
      {text.trim().split(/\n{2,}/).map((para, i) => (
        <p key={i}>{inline(para).map((t, j) => (t.kind === "code" ? <code key={j}>{t.value}</code> : t.kind === "bold" ? <strong key={j}>{t.value}</strong> : <Fragment key={j}>{t.value}</Fragment>))}</p>
      ))}
    </>
  );
}

function FieldTable({ caption, rows }: { caption: string; rows: ReturnType<typeof fields> }) {
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <caption className="pb-1 text-left font-semibold">{caption}</caption>
        <thead><tr><th scope="col" className="border-b-2 border-border py-1 pr-4">Name</th><th scope="col" className="border-b-2 border-border py-1 pr-4">Type</th><th scope="col" className="border-b-2 border-border py-1 pr-4">Required</th><th scope="col" className="border-b-2 border-border py-1">Description</th></tr></thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.name} className="align-top">
              <th scope="row" className="border-b border-border-subtle py-1 pr-4 font-mono font-normal">{f.name}</th>
              <td className="border-b border-border-subtle py-1 pr-4">{f.type}</td>
              <td className="border-b border-border-subtle py-1 pr-4">{f.required ? "Yes" : "No"}</td>
              <td className="border-b border-border-subtle py-1">{f.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OperationDoc({ spec, method, path, op, base }: { spec: Spec; method: string; path: string; op: Operation; base: string }) {
  const id = `op-${op.operationId}`;
  const body = op.requestBody?.content["application/json"]?.schema;
  const example = exampleOf(spec, body);
  const command = curl(base, method, path, op, example);
  const ok = Object.entries(op.responses).find(([c]) => c.startsWith("2"));
  const okSchema = ok?.[1].content?.["application/json"]?.schema;
  const okFields = fields(spec, resolve(spec, okSchema)?.type === "array" ? resolve(spec, okSchema)?.items : okSchema);
  const params = (op.parameters ?? []).map((p) => ({ name: `${p.name} (${p.in})`, type: resolve(spec, p.schema)?.type ?? "string", required: !!p.required, description: p.description ?? "" }));
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 border-t border-border pt-4">
      <h3 id={id} className="text-lg font-bold"><span className="font-mono">{method.toUpperCase()} {path}</span><span className="a11y-sr-only">: </span> <span className="block text-base font-semibold">{op.summary}</span></h3>
      <Text text={op.description} />
      <FieldTable caption="Parameters" rows={params} />
      {body && <FieldTable caption={`Request body (${refName(body)})`} rows={fields(spec, body)} />}
      <div>
        <p className="font-semibold">Example request</p>
        <pre className="whitespace-pre-wrap rounded border border-border p-3 [overflow-wrap:anywhere]"><code>{command}</code></pre>
        <Button variant="secondary" onPress={() => void navigator.clipboard?.writeText(command)}>Copy example<span className="a11y-sr-only"> for {op.summary}</span></Button>
      </div>
      {okFields.length > 0 && <FieldTable caption={`Response ${ok?.[0]} (${refName(resolve(spec, okSchema)?.type === "array" ? resolve(spec, okSchema)?.items : okSchema) ?? "object"})`} rows={okFields} />}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <caption className="pb-1 text-left font-semibold">Responses</caption>
          <thead><tr><th scope="col" className="border-b-2 border-border py-1 pr-4">Status</th><th scope="col" className="border-b-2 border-border py-1">Meaning</th></tr></thead>
          <tbody>
            {Object.entries(op.responses).filter(([c]) => c !== "422").map(([code, r]) => (
              <tr key={code} className="align-top"><th scope="row" className="border-b border-border-subtle py-1 pr-4 font-mono font-normal">{code}</th><td className="border-b border-border-subtle py-1">{r.description}</td></tr>
            ))}
            {op.responses["422"] && <tr className="align-top"><th scope="row" className="border-b border-border-subtle py-1 pr-4 font-mono font-normal">422</th><td className="border-b border-border-subtle py-1">The request is not valid. <code>field</code> names the problem.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Reference() {
  const [spec, setSpec] = useState<Spec | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void fetch("/api/v1/openapi.json").then(async (r) => (r.ok ? setSpec((await r.json()) as Spec) : setError("The API description could not be loaded."))).catch(() => setError("We could not reach the server. Check your connection and try again."));
  }, []);
  if (error) return <StatusMessage>{error}</StatusMessage>;
  if (!spec) return <p role="status">Loading the API description.</p>;

  const base = typeof window !== "undefined" ? window.location.origin.replace(/:3000$/, ":8010") : "";
  const groups = (spec.tags ?? []).map((t) => ({
    name: t.name,
    ops: Object.entries(spec.paths).flatMap(([path, item]) =>
      Object.entries(item).filter(([m, o]) => METHOD_ORDER.includes(m) && o.tags?.includes(t.name)).map(([method, op]) => ({ path, method, op })),
    ),
  })).filter((g) => g.ops.length);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
      <nav aria-label="API sections" className="flex flex-col gap-3 lg:sticky lg:top-4 lg:self-start">
        <h2 className="text-lg font-bold">On this page</h2>
        <ul className="flex flex-col gap-1">
          <li><a className="underline" href="#overview">Overview</a></li>
          <li><a className="underline" href="#errors">Errors and limits</a></li>
          <li><a className="underline" href="#webhooks">Webhooks</a></li>
          {groups.map((g) => (
            <li key={g.name}>
              <a className="underline" href={`#group-${g.name}`}>{g.name}</a>
              <ul className="ml-4 list-disc">{g.ops.map((o) => <li key={o.op.operationId}><a className="underline" href={`#op-${o.op.operationId}`}>{o.op.summary}</a></li>)}</ul>
            </li>
          ))}
        </ul>
        <p><a className="underline" href="/api/v1/openapi.json">Download the OpenAPI description (JSON)</a></p>
      </nav>
      <div className="flex min-w-0 flex-col gap-8">
        <section aria-labelledby="overview" className="flex max-w-prose flex-col gap-2">
          <h2 id="overview" className="text-xl font-bold">Overview <span className="text-base font-normal">(version {spec.info.version})</span></h2>
          <Text text={spec.info.description} />
        </section>
        <section aria-labelledby="errors" className="flex max-w-prose flex-col gap-2">
          <h2 id="errors" className="text-xl font-bold">Errors and limits</h2>
          <p>Errors use the same JSON shape everywhere:</p>
          <pre className="whitespace-pre-wrap rounded border border-border p-3 [overflow-wrap:anywhere]"><code>{`{ "detail": "You have used 10 of 10 this month. Upgrade your plan for more.", "code": "quota_exceeded" }`}</code></pre>
          <p>Common codes: <code>invalid_api_key</code> (401), <code>scope_missing</code> and <code>api_not_in_plan</code> (403), <code>quota_exceeded</code> (402), <code>rate_limited</code> (429, wait <code>Retry-After</code> seconds).</p>
        </section>
        <section aria-labelledby="webhooks" className="flex max-w-prose flex-col gap-3">
          <h2 id="webhooks" className="text-xl font-bold">Webhooks</h2>
          <p>Instead of asking whether a scan has finished, give us an address and we tell you. Add one under <em>Organisation → Webhooks</em>; each has a signing secret that is shown once.</p>
          <h3 className="text-lg font-semibold">Events</h3>
          <ul className="list-disc pl-6">
            <li><code>scan.completed</code>: a scan finished successfully (<code>scan_id</code>, <code>url</code>, <code>findings</code>, <code>critical_or_serious</code>, <code>api_path</code>).</li>
            <li><code>scan.failed</code>: a scan did not finish (<code>scan_id</code>, <code>url</code>, <code>reason</code>, <code>credit_returned</code>).</li>
            <li><code>report.ready</code>: a report can be downloaded (<code>report_id</code>, <code>scan_id</code>, <code>kind</code>, <code>download_path</code>).</li>
            <li><code>report.failed</code>: a report could not be produced (<code>report_id</code>, <code>reason</code>).</li>
            <li><code>ping</code>: only when you press <em>Send a test</em>.</li>
          </ul>
          <h3 className="text-lg font-semibold">The request</h3>
          <p>We send <code>POST</code> with a JSON body and these headers: <code>A11y-Event-Id</code> (the same for every retry, use it to ignore duplicates), <code>A11y-Event-Type</code>, <code>A11y-Delivery-Attempt</code> and <code>A11y-Signature</code>.</p>
          <pre className="whitespace-pre-wrap rounded border border-border p-3 [overflow-wrap:anywhere]"><code>{`{ "id": "6f1c...", "type": "scan.completed", "created_at": "2026-11-28T09:15:00+00:00",
  "data": { "scan_id": "b1c2...", "url": "https://www.example.com/", "findings": 12, "critical_or_serious": 3, "api_path": "/v1/scans/b1c2..." } }`}</code></pre>
          <h3 className="text-lg font-semibold">Check the signature</h3>
          <p>The header looks like <code>t=1764321300,v1=9a3f...</code>. Compute an HMAC-SHA256 of <code>&quot;&lt;t&gt;.&lt;raw body&gt;&quot;</code> with your signing secret and compare it with <code>v1</code> using a constant-time comparison. Reject requests whose <code>t</code> is more than five minutes old. Use the raw bytes of the body, not a re-serialised copy.</p>
          <pre className="whitespace-pre-wrap rounded border border-border p-3 [overflow-wrap:anywhere]"><code>{SAMPLE}</code></pre>
          <h3 className="text-lg font-semibold">Answering, retries and limits</h3>
          <p>Answer with any <code>2xx</code> status within 10 seconds. Anything else, or no answer, is retried after 1 minute, 5 minutes, 30 minutes, 2 hours and 6 hours, then given up on; you can retry a delivery by hand. <code>410 Gone</code> switches the webhook off. Redirects are not followed, and addresses on private networks are refused.</p>
        </section>
        {groups.map((g) => (
          <section key={g.name} aria-labelledby={`group-${g.name}`} className="flex flex-col gap-6">
            <h2 id={`group-${g.name}`} className="text-xl font-bold">{g.name}</h2>
            {g.ops.map((o) => <OperationDoc key={o.op.operationId} spec={spec} base={base} {...o} />)}
          </section>
        ))}
      </div>
    </div>
  );
}

export default function DevelopersPage() {
  return (
    <Page title="API reference" intro="Start accessibility scans, read their findings and download accessible reports from your own systems.">
      <Reference />
    </Page>
  );
}
