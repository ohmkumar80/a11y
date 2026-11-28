import type { Page } from "@playwright/test";

const item = (id: string, title: string, read: boolean, link: string | null) => ({
  id, event: "scan.completed", title, body: "The scan of https://example.com/ has finished. 12 problems, 3 of them critical or serious.", link, created_at: "2026-11-27T01:00:00Z", read,
});

/** A stateful fake of /me/notifications. */
export async function mockNotifications(page: Page, opts: { empty?: boolean } = {}) {
  const items = opts.empty ? [] : [item("n1", "Your accessibility scan of https://example.com/ is ready", false, "/workspace/scan?id=11111111-aaaa-4bbb-8ccc-111111111111"), item("n2", "You have used all your scans this month", false, "/org#plan"), item("n3", "Your free trial has ended", true, "/org#plan")];
  const prefs = { email_scan: true };
  const calls: string[] = [];
  const unread = () => items.filter((i) => !i.read).length;
  await page.route("**/api/me/notifications?*", (r) => r.fulfill({ json: { unread: unread(), items, next_before: null } }));
  await page.route("**/api/me/notifications/read", (r) => {
    const b = r.request().postDataJSON() as { ids?: string[]; all?: boolean };
    for (const i of items) if (b.all || b.ids?.includes(i.id)) i.read = true;
    calls.push(b.all ? "read-all" : `read:${b.ids?.join(",")}`);
    return r.fulfill({ json: { unread: unread() } });
  });
  await page.route("**/api/me/notification-preferences", (r) => {
    if (r.request().method() === "PUT") { Object.assign(prefs, r.request().postDataJSON()); calls.push(`prefs:${prefs.email_scan}`); }
    return r.fulfill({ json: prefs });
  });
  return { calls, prefs };
}
