"use client";

import NextLink from "next/link";
import { useRef, useState } from "react";
import { Button, Checkbox, Dialog, DialogTrigger, ErrorSummary, Form, StatusMessage, Table, TextField, notify } from "@a11y/ui";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { useForm } from "@/components/useForm";
import { del, patch, post } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";
import { DELIVERY_STATE, type Delivery, type Endpoint, type EndpointList, type NewEndpoint } from "@/lib/webhooks";

function Secret({ title, secret, onDone }: { title: string; secret: string; onDone: () => void }) {
  const ref = useRef<HTMLHeadingElement>(null);
  return (
    <section aria-labelledby="new-secret" className="flex flex-col gap-3 rounded border-2 border-border p-4">
      <h2 id="new-secret" ref={(el) => { ref.current = el; el?.focus(); }} tabIndex={-1} className="text-xl font-bold">{title}</h2>
      <p><strong>This is the only time the secret is shown.</strong> Use it in your receiver to check the <code>A11y-Signature</code> header of each request. Store it in a secret manager.</p>
      <p><code className="block [overflow-wrap:anywhere] rounded border border-border bg-surface-raised p-3 select-all">{secret}</code></p>
      <div className="flex flex-wrap gap-3">
        <Button variant="secondary" onPress={async () => { await navigator.clipboard?.writeText(secret); notify({ title: "Secret copied", kind: "success" }); }}>Copy secret</Button>
        <Button variant="secondary" onPress={onDone}>I have stored it safely</Button>
      </div>
    </section>
  );
}

function Deliveries({ endpoint, onRetried }: { endpoint: Endpoint; onRetried: () => void }) {
  const list = useApi<Delivery[]>(`/org/webhooks/${endpoint.id}/deliveries`);
  const [message, setMessage] = useState("");
  return (
    <section aria-labelledby="deliveries" className="flex flex-col gap-3">
      <h2 id="deliveries" className="text-xl font-bold">Recent deliveries to {endpoint.url}</h2>
      <p role="status">{message}</p>
      <div><Button variant="secondary" onPress={() => void list.reload()}>Refresh deliveries</Button></div>
      <Table<Delivery>
        label="Recent deliveries"
        rows={list.data ?? []}
        rowKey={(d) => d.id}
        emptyText={list.data ? "Nothing has been sent to this address yet." : "Loading."}
        columns={[
          { id: "e", header: "Event", isRowHeader: true, render: (d) => d.event_type },
          { id: "s", header: "State", render: (d) => `${DELIVERY_STATE[d.status] ?? d.status}${d.error ? `: ${d.error}` : ""}` },
          { id: "a", header: "Tries", render: (d) => String(d.attempts) },
          { id: "w", header: "When", render: (d) => formatDate(d.created_at) },
          {
            id: "r", header: "Action",
            render: (d) => d.status === "ABANDONED" ? (
              <Button variant="secondary" onPress={async () => {
                const r = await post(`/org/webhooks/deliveries/${d.id}/retry`);
                setMessage(r.ok ? "Retrying now." : r.problem.detail);
                if (r.ok) { void list.reload(); onRetried(); }
              }}>Retry<span className="a11y-sr-only"> {d.event_type} delivery</span></Button>
            ) : null,
          },
        ]}
      />
    </section>
  );
}

function Content() {
  const state = useApi<EndpointList>("/org/webhooks");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [secret, setSecret] = useState<{ title: string; value: string } | null>(null);
  const [selected, setSelected] = useState<Endpoint | null>(null);
  const [message, setMessage] = useState("");
  const form = useForm();

  if (state.error) return <StatusMessage>{state.error.detail}</StatusMessage>;
  if (!state.data) return <p role="status">Loading.</p>;
  const d = state.data;
  if (!d.entitled) {
    return <StatusMessage>{d.switched_off ? "Webhooks are switched off for your account at the moment." : <>Webhooks are part of API access, which is not in your current plan. <NextLink href={d.upgrade_url} className="underline">See plans</NextLink>.</>}</StatusMessage>;
  }

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <p>
        A webhook tells your own system when something happens, such as a scan finishing, so it does not have to keep asking. We send a signed JSON request to the address you give.
        See the <NextLink href="/developers#webhooks" className="underline">API reference</NextLink> for the format and how to check the signature.
      </p>
      {secret && <Secret title={secret.title} secret={secret.value} onDone={() => setSecret(null)} />}

      <section aria-labelledby="endpoints" className="flex flex-col gap-3">
        <h2 id="endpoints" className="text-xl font-bold">Your webhooks</h2>
        <p role="status">{message || `${d.endpoints.length} of ${d.max_endpoints} webhooks.`}</p>
        <Table<Endpoint>
          label="Webhooks"
          rows={d.endpoints}
          rowKey={(e) => e.id}
          emptyText="You have no webhooks yet."
          columns={[
            { id: "u", header: "Address", isRowHeader: true, render: (e) => <><span className="[overflow-wrap:anywhere]">{e.url}</span>{e.description && <span className="block text-sm text-fg-muted">{e.description}</span>}</> },
            { id: "ev", header: "Events", render: (e) => e.events.join(", ") },
            { id: "s", header: "State", render: (e) => (e.enabled ? "On" : `Off: ${e.disabled_reason ?? ""}`) },
            { id: "l", header: "Last delivery", render: (e) => (e.last_delivery ? `${DELIVERY_STATE[e.last_delivery.status] ?? e.last_delivery.status}${e.last_delivery.error ? ` (${e.last_delivery.error})` : ""}` : "None yet") },
            {
              id: "a", header: "Actions",
              render: (e) => (
                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" onPress={() => setSelected(e)}>Deliveries<span className="a11y-sr-only"> for {e.url}</span></Button>
                  <Button variant="secondary" onPress={async () => { const r = await post(`/org/webhooks/${e.id}/test`); setMessage(r.ok ? "A test event was queued. Refresh the deliveries to see the result." : r.problem.detail); }}>Send a test<span className="a11y-sr-only"> to {e.url}</span></Button>
                  <Button variant="secondary" onPress={async () => { const r = await patch(`/org/webhooks/${e.id}`, { enabled: !e.enabled }); setMessage(r.ok ? `The webhook is now ${e.enabled ? "off" : "on"}.` : r.problem.detail); void state.reload(); }}>{e.enabled ? "Turn off" : "Turn on"}<span className="a11y-sr-only"> {e.url}</span></Button>
                  <DialogTrigger>
                    <Button variant="secondary">Rotate secret<span className="a11y-sr-only"> for {e.url}</span></Button>
                    <Dialog title="Rotate the signing secret?">
                      {(close) => (
                        <>
                          <p>The old secret stops working immediately. Update your receiver with the new one straight away, or its checks will fail.</p>
                          <div><Button onPress={async () => { const r = await post<{ secret: string }>(`/org/webhooks/${e.id}/rotate-secret`); close(); if (r.ok) setSecret({ title: "Your new signing secret: copy it now", value: r.data.secret }); else setMessage(r.problem.detail); void state.reload(); }}>Rotate secret</Button></div>
                        </>
                      )}
                    </Dialog>
                  </DialogTrigger>
                  <DialogTrigger>
                    <Button variant="secondary">Delete<span className="a11y-sr-only"> {e.url}</span></Button>
                    <Dialog title="Delete this webhook?">
                      {(close) => (
                        <>
                          <p>We stop sending events to this address and remove its delivery history. This cannot be undone.</p>
                          <div><Button onPress={async () => { const r = await del(`/org/webhooks/${e.id}`); close(); setMessage(r.ok ? "The webhook was deleted." : r.problem.detail); if (selected?.id === e.id) setSelected(null); void state.reload(); }}>Delete webhook</Button></div>
                        </>
                      )}
                    </Dialog>
                  </DialogTrigger>
                </div>
              ),
            },
          ]}
        />
      </section>

      {selected && <Deliveries endpoint={selected} onRetried={() => void state.reload()} />}

      <section aria-labelledby="create" className="flex max-w-xl flex-col gap-3">
        <h2 id="create" className="text-xl font-bold">Add a webhook</h2>
        <ErrorSummary errors={form.errors} />
        <Form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (events.length === 0) { await form.submit(async () => ({ detail: "Choose at least one event.", field: "events" })); return; }
            const ok = await form.submit(async () => {
              const r = await post<NewEndpoint>("/org/webhooks", { url, events, description });
              if (!r.ok) return r.problem;
              setSecret({ title: "Your signing secret: copy it now", value: r.data.secret });
              return null;
            });
            if (ok) { setUrl(""); setDescription(""); setEvents([]); void state.reload(); }
          }}
        >
          <TextField id="field-url" label="Address" type="url" description="Must start with https://. Addresses on private networks are not allowed." value={url} onChange={setUrl} isRequired error={form.fieldError("url")} />
          <TextField id="field-description" label="Description (optional)" value={description} onChange={setDescription} />
          <fieldset id="field-events" className="flex flex-col gap-1">
            <legend className="font-semibold">Events to send</legend>
            {Object.entries(d.events).map(([id, label]) => (
              <Checkbox key={id} label={`${label} (${id})`} isSelected={events.includes(id)} onChange={(on) => setEvents((s) => (on ? [...s, id] : s.filter((x) => x !== id)))} />
            ))}
            {form.fieldError("events") && <p className="text-sm font-medium text-danger">{form.fieldError("events")}</p>}
          </fieldset>
          <Button type="submit" isPending={form.submitting} pendingLabel="Adding webhook" isDisabled={d.endpoints.length >= d.max_endpoints}>Add webhook</Button>
          {d.endpoints.length >= d.max_endpoints && <p>You have the most webhooks your organisation can have. Delete one to add another.</p>}
        </Form>
      </section>
    </div>
  );
}

export default function WebhooksPage() {
  return (
    <RequireAuth requiredRole="COMPANY_ADMIN">
      {() => (
        <Page title="Webhooks" intro="Get a signed message at your own address when a scan or report finishes.">
          <p><NextLink href="/org" className="underline">Back to your organisation</NextLink></p>
          <Content />
        </Page>
      )}
    </RequireAuth>
  );
}
