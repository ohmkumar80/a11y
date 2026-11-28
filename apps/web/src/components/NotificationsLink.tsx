"use client";

import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { useFlags } from "@/lib/flags";
import type { NotificationList } from "@/lib/notifications";

const navLink =
  "inline-flex min-h-11 items-center rounded-lg px-3 font-medium underline-offset-4 hover:bg-bg-subtle hover:underline aria-[current=page]:bg-accent-subtle aria-[current=page]:font-bold aria-[current=page]:text-accent aria-[current=page]:underline";
const REFRESH_MS = 60_000;

/** Header link with the number of unread notifications. It refreshes quietly (on each page and once a minute while the tab
 *  is visible); there is no live region, so nothing is announced unless the person goes to look. */
export function NotificationsLink() {
  const flags = useFlags();
  const path = usePathname();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!flags.notification_center) return;
    let alive = true;
    const load = async () => {
      if (document.visibilityState === "hidden") return;
      const r = await get<NotificationList>("/me/notifications?limit=1");
      if (alive && r.ok) setUnread(r.data.unread);
    };
    void load();
    const t = setInterval(() => void load(), REFRESH_MS);
    return () => { alive = false; clearInterval(t); };
  }, [flags.notification_center, path]);

  if (!flags.notification_center) return null;
  return (
    <NextLink href="/notifications" aria-current={path === "/notifications" ? "page" : undefined} className={navLink}>
      Notifications{unread > 0 && <span className="ml-1 rounded-full border-2 border-accent bg-accent-subtle px-2 text-sm font-bold text-accent">{unread}<span className="a11y-sr-only"> unread</span></span>}
    </NextLink>
  );
}
