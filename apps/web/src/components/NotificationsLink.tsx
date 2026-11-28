"use client";

import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { get } from "@/lib/api";
import { useFlags } from "@/lib/flags";
import type { NotificationList } from "@/lib/notifications";

const REFRESH_MS = 60_000;

/** Navigation link with the number of unread notifications. It refreshes quietly (on each page and once a minute while the
 *  tab is visible); there is no live region, so nothing is announced unless the person goes to look. */
export function NotificationsLink({ className, icon }: { className: string; icon?: ReactNode }) {
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
    <NextLink href="/notifications" aria-current={path === "/notifications" ? "page" : undefined} className={className}>
      {icon}
      Notifications{unread > 0 && <span className="ml-auto rounded-sm bg-inverse-accent px-1.5 text-sm font-bold text-inverse-bg">{unread}<span className="a11y-sr-only"> unread</span></span>}
    </NextLink>
  );
}
