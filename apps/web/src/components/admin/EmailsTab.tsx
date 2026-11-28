"use client";

import { useRef, useState } from "react";
import { Button, Checkbox, ErrorSummary, Form, StatusMessage, Table, TextArea, TextField, notify } from "@a11y/ui";
import { post, put } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";
import { useForm } from "../useForm";

interface EventInfo {
  key: string; label: string; audience: string; category: string; required: boolean; variables: Record<string, string>; has_link: boolean;
  default: { subject: string; intro: string; action_label: string; outro: string }; enabled: boolean; edited: boolean;
}
interface Override { event: string; enabled: boolean; subject: string; intro: string; action_label: string; outro: string }
interface Saved { value: { items: Override[] } }
interface Preview { subject: string; text: string; html: string; accessibility_problems: string[] }
interface LogRow { id: string; label: string; to: string; state: string; attempts: number; error: string | null; organisation: string; created_at: string }

const AUDIENCE: Record<string, string> = { user: "The person the email is for", actor: "Whoever started the scan", org_admins: "Organisation administrators" };
const STATE: Record<string, string> = { QUEUED: "Waiting to send", SENT: "Sent", FAILED: "Failed", SKIPPED: "Not sent (switched off)" };
const blank = (event: string): Override => ({ event, enabled: true, subject: "", intro: "", action_label: "", outro: "" });

/** Edit the wording of each email (the layout is fixed, so every email stays accessible), preview a draft, send a test
 *  to yourself and watch delivery. Saving goes through the same versioned, audited settings path as everything else. */
export function EmailsTab() {
  const events = useApi<EventInfo[]>("/admin/notifications/events");
  const saved = useApi<Saved>("/admin/settings/notify.templates?scope=global&scope_id=");
  const log = useApi<LogRow[]>("/admin/notifications/log?limit=25");
  const [editing, setEditing] = useState<EventInfo | null>(null);
  const [draft, setDraft] = useState<Override | null>(null);
  const [comment, setComment] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const form = useForm();

  const items = saved.data?.value.items ?? [];

  function edit(ev: EventInfo) {
    setEditing(ev);
    setDraft(items.find((i) => i.event === ev.key) ?? blank(ev.key));
    setPreview(null);
    setPreviewError(null);
    setComment("");
    requestAnimationFrame(() => heading.current?.focus());
  }

  async function runPreview() {
    if (!draft) return;
    setPreviewError(null);
    const r = await post<Preview>("/admin/notifications/preview", draft);
    if (r.ok) setPreview(r.data); else { setPreview(null); setPreviewError(r.problem.detail); }
  }

  async function sendTest(ev: EventInfo) {
    const r = await post<{ sent_to: string }>("/admin/notifications/test", { event: ev.key });
    setMessage(r.ok ? `A test of “${ev.label}” was sent to ${r.data.sent_to}.` : r.problem.detail);
  }

  const set = (k: keyof Override) => (v: string | boolean) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const untouched = (d: Override) => d.enabled && !d.subject && !d.intro && !d.action_label && !d.outro;

  return (
    <div className="a11y-page-body flex flex-col gap-6">
      <p className="max-w-3xl text-fg-muted">
        You can change what each email says, or switch it off. The layout is fixed, so every email keeps its structure, contrast and a plain-text version.
        Changes are versioned and audited like every other setting.
      </p>
      {message && <p role="status" className="font-semibold">{message}</p>}
      <Table<EventInfo>
        label="Emails the platform sends"
        rows={events.data ?? []}
        rowKey={(e) => e.key}
        emptyText={events.data ? "No emails." : "Loading emails."}
        columns={[
          { id: "n", header: "Email", isRowHeader: true, render: (e) => e.label },
          { id: "a", header: "Sent to", render: (e) => AUDIENCE[e.audience] ?? e.audience },
          { id: "s", header: "State", render: (e) => `${e.enabled ? "On" : "Off"}${e.edited ? ", wording changed" : ", built-in wording"}` },
          {
            id: "x", header: "Actions",
            render: (e) => (
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onPress={() => edit(e)}>Edit<span className="a11y-sr-only"> {e.label}</span></Button>
                <Button variant="secondary" onPress={() => void sendTest(e)}>Send a test to me<span className="a11y-sr-only">: {e.label}</span></Button>
              </div>
            ),
          },
        ]}
      />

      {editing && draft && (
        <section aria-labelledby="email-editor" className="flex max-w-3xl flex-col gap-4 rounded border border-border p-4">
          <h2 id="email-editor" ref={heading} tabIndex={-1} className="text-xl font-bold">Edit: {editing.label}</h2>
          <p>
            Leave a field empty to keep the built-in text, shown in the box until you type.
            {Object.keys(editing.variables).length > 0 && <> You can put these in the text, and they are filled in for each email: {Object.entries(editing.variables).map(([k, d]) => <span key={k}><code>{`{${k}}`}</code> ({d}) </span>)}</>}
          </p>
          <ErrorSummary errors={form.errors} />
          <Form
            className="flex flex-col gap-4"
            onSubmit={async (e) => {
              e.preventDefault();
              const rest = items.filter((i) => i.event !== editing.key);
              const next = untouched(draft) ? rest : [...rest, draft];
              const ok = await form.submit(async () => {
                const r = await put("/admin/settings/notify.templates", { scope: "global", scope_id: "", value: { items: next }, comment, publish: true });
                return r.ok ? null : { ...r.problem, field: undefined };
              });
              if (ok) {
                notify({ title: "Email saved", description: `${editing.label} is updated.`, kind: "success" });
                setEditing(null);
                void saved.reload();
                void events.reload();
              }
            }}
          >
            <Checkbox
              label={`Send this email${editing.required ? " (always on: people could not sign in or join without it)" : ""}`}
              isSelected={draft.enabled}
              isDisabled={editing.required}
              onChange={(v) => set("enabled")(v)}
            />
            <TextField id="field-subject" label="Subject" placeholder={editing.default.subject} value={draft.subject} onChange={set("subject")} />
            <TextArea label="Introduction" rows={3} value={draft.intro} onChange={set("intro")} description={`Built-in: ${editing.default.intro}`} />
            {editing.has_link && (
              <TextField id="field-action_label" label="Link text" description="Say what the link does, for example “View the results”. Not “click here”." placeholder={editing.default.action_label} value={draft.action_label} onChange={set("action_label")} />
            )}
            <TextArea label="Closing line" rows={2} value={draft.outro} onChange={set("outro")} description={`Built-in: ${editing.default.outro}`} />
            <TextField id="field-comment" label="Why are you changing it?" description="Recorded in the history." value={comment} onChange={setComment} isRequired />
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onPress={() => void runPreview()}>Preview this draft</Button>
              <Button type="submit" isPending={form.submitting} pendingLabel="Saving">Save</Button>
              <Button variant="secondary" onPress={() => setEditing(null)}>Cancel</Button>
            </div>
          </Form>
          {previewError && <StatusMessage>{previewError}</StatusMessage>}
          {preview && (
            <div className="flex flex-col gap-2" aria-live="polite">
              <h3 className="text-lg font-semibold">Preview with sample data</h3>
              <p><span className="font-semibold">Subject:</span> {preview.subject}</p>
              <p className="font-semibold">
                {preview.accessibility_problems.length === 0 ? "Accessibility check: passed." : `Accessibility check: ${preview.accessibility_problems.join("; ")}.`}
              </p>
              <iframe title={`Preview of the email: ${editing.label}`} sandbox="" srcDoc={preview.html} className="h-80 w-full rounded border border-border bg-white" />
              <details>
                <summary>Plain-text version</summary>
                <pre className="overflow-x-auto whitespace-pre-wrap rounded border border-border p-2">{preview.text}</pre>
              </details>
            </div>
          )}
        </section>
      )}

      <section aria-labelledby="email-log" className="flex flex-col gap-3">
        <h2 id="email-log" className="text-xl font-bold">Recent emails</h2>
        <div><Button variant="secondary" onPress={() => void log.reload()}>Refresh the list</Button></div>
        <Table<LogRow>
          label="Recent emails across all organisations"
          rows={log.data ?? []}
          rowKey={(r) => r.id}
          emptyText={log.data ? "Nothing has been sent yet." : "Loading."}
          columns={[
            { id: "e", header: "Email", isRowHeader: true, render: (r) => r.label },
            { id: "o", header: "Organisation", render: (r) => r.organisation },
            { id: "t", header: "To", render: (r) => <span className="[overflow-wrap:anywhere]">{r.to}</span> },
            { id: "s", header: "State", render: (r) => `${STATE[r.state] ?? r.state}${r.state === "FAILED" && r.error ? `: ${r.error}` : ""}` },
            { id: "w", header: "Created", render: (r) => formatDate(r.created_at) },
          ]}
        />
      </section>
    </div>
  );
}

