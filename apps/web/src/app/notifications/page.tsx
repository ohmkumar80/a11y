"use client";

import NextLink from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button, Checkbox, StatusMessage } from "@a11y/ui";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { get, post, put } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import type { NotificationItem, NotificationList } from "@/lib/notifications";

function Content() {
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [more, setMore] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [emailScan, setEmailScan] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await get<NotificationList>("/me/notifications?limit=20");
    if (!r.ok) { setError(r.problem.detail); return; }
    setItems(r.data.items); setUnread(r.data.unread); setMore(r.data.next_before);
  }, []);
  useEffect(() => {
    void load();
    void get<{ email_scan: boolean }>("/me/notification-preferences").then((r) => r.ok && setEmailScan(r.data.email_scan));
  }, [load]);

  async function read(ids: string[] | "all") {
    const r = await post<{ unread: number }>("/me/notifications/read", ids === "all" ? { all: true } : { ids });
    if (r.ok) {
      setUnread(r.data.unread);
      setItems((prev) => prev && prev.map((i) => (ids === "all" || ids.includes(i.id) ? { ...i, read: true } : i)));
      setMessage(r.data.unread === 0 ? "All notifications are marked as read." : `${r.data.unread} unread.`);
    }
  }

  if (error) return <StatusMessage>{error}</StatusMessage>;
  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <section aria-labelledby="list" className="flex flex-col gap-3">
        <h2 id="list" className="text-xl font-bold">Your notifications</h2>
        <p role="status">{message || (items ? `${unread} unread.` : "Loading.")}</p>
        {unread > 0 && <div><Button variant="secondary" onPress={() => void read("all")}>Mark all as read</Button></div>}
        {items && items.length === 0 && <p>You have no notifications yet. We tell you here when a scan finishes or something needs your attention.</p>}
        <ul className="flex flex-col gap-3">
          {(items ?? []).map((i) => (
            <li key={i.id} className={`rounded border p-3 ${i.read ? "border-border-subtle" : "border-2 border-border"}`}>
              <h3 className="text-base font-semibold">
                {!i.read && <span className="mr-2 rounded border border-border px-1.5 text-sm">Unread</span>}
                {i.link ? <NextLink href={i.link} className="underline" onClick={() => !i.read && void read([i.id])}>{i.title}</NextLink> : i.title}
              </h3>
              <p>{i.body}</p>
              <p className="text-sm text-fg-muted">{formatDate(i.created_at)}</p>
              {!i.read && <Button variant="secondary" onPress={() => void read([i.id])}>Mark as read<span className="a11y-sr-only">: {i.title}</span></Button>}
            </li>
          ))}
        </ul>
        {more && (
          <div><Button variant="secondary" onPress={async () => {
            const r = await get<NotificationList>(`/me/notifications?limit=20&before=${encodeURIComponent(more)}`);
            if (r.ok) { setItems((prev) => [...(prev ?? []), ...r.data.items]); setMore(r.data.next_before); }
          }}>Show older notifications</Button></div>
        )}
      </section>

      <section aria-labelledby="prefs" className="flex flex-col gap-3">
        <h2 id="prefs" className="text-xl font-bold">Email</h2>
        <p>We always email you about your account, security and billing. You can choose whether to get an email when a scan finishes or fails. You will still see it here.</p>
        {emailScan !== null && (
          <Checkbox
            label="Email me when a scan finishes or fails"
            isSelected={emailScan}
            onChange={async (on) => {
              setEmailScan(on);
              const r = await put("/me/notification-preferences", { email_scan: on });
              setMessage(r.ok ? (on ? "You will get scan emails." : "You will not get scan emails.") : r.problem.detail);
              if (!r.ok) setEmailScan(!on);
            }}
          />
        )}
      </section>
    </div>
  );
}

export default function NotificationsPage() {
  return (
    <RequireAuth>
      {(user) => (
        <Page title="Notifications" intro="What happened in your organisation, and how we email you about it.">
          {user.role === "SUPER_ADMIN" || user.role === "REVIEWER" ? <StatusMessage>Platform staff do not have a notification list. Use the <NextLink href="/admin" className="underline">admin console</NextLink>.</StatusMessage> : <Content />}
        </Page>
      )}
    </RequireAuth>
  );
}
