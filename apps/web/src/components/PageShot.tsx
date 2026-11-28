"use client";

import { useEffect, useState } from "react";
import { getBlobUrl } from "@/lib/api";
import type { PageShotMeta, Rect } from "@/lib/scans";

const cache = new Map<string, Promise<string | null>>();
function load(scanId: string, pageId: string) {
  const key = `${scanId}/${pageId}`;
  if (!cache.has(key)) cache.set(key, getBlobUrl(`/scans/${scanId}/pages/${pageId}/screenshot`).then((r) => (r.ok ? r.url : null)));
  return cache.get(key)!;
}

const PAD = 56, MIN_W = 480, MIN_H = 270;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const pct = (n: number) => `${n * 100}%`;

/** Where the element sits in the saved picture, or why we cannot show it. Positions are in page pixels. */
export function visibility(rect: Rect | null | undefined, shot: PageShotMeta): "ok" | "hidden" | "below" {
  if (!rect || rect.w <= 0 || rect.h <= 0 || rect.x >= shot.width || rect.x + rect.w <= 0) return "hidden";
  if (rect.y >= shot.height) return "below";
  return "ok";
}

export function cropFor(rect: Rect, shot: PageShotMeta) {
  const cw = Math.min(shot.width, Math.max(MIN_W, rect.w + 2 * PAD));
  const ch = Math.min(shot.height, Math.max(MIN_H, rect.h + 2 * PAD));
  return {
    cx: clamp(rect.x - (cw - rect.w) / 2, 0, shot.width - cw),
    cy: clamp(rect.y - (ch - rect.h) / 2, 0, shot.height - ch),
    cw, ch,
  };
}

/** The saved picture of a page with one element outlined. The outline is a white ring inside a dark-red ring, so it
 *  shows on light and dark backgrounds and does not depend on colour alone. The picture is also described in words:
 *  see `describe`, and the element's HTML shown beside it. */
export function PageShot({ scanId, pageId, pageUrl, shot, rect, whole }: {
  scanId: string; pageId: string; pageUrl: string; shot: PageShotMeta; rect: Rect | null | undefined; whole: boolean;
}) {
  const [src, setSrc] = useState<string | null | undefined>(undefined);
  useEffect(() => { let alive = true; void load(scanId, pageId).then((u) => alive && setSrc(u)); return () => { alive = false; }; }, [scanId, pageId]);

  const vis = visibility(rect, shot);
  const box = whole || vis !== "ok" ? { cx: 0, cy: 0, cw: shot.width, ch: shot.height } : cropFor(rect!, shot);
  if (src === undefined) return <p>Loading the screenshot…</p>;
  if (src === null) return <p>We could not load the screenshot. The element&apos;s HTML below still shows what is wrong.</p>;

  const image = (
    <div className="relative w-full overflow-hidden border border-border" style={{ aspectRatio: `${box.cw} / ${box.ch}` }}>
      <img
        src={src}
        alt={`Screenshot of ${pageUrl}${whole || vis !== "ok" ? "" : ", zoomed in on the element with the problem, which is outlined"}.`}
        style={{ position: "absolute", maxWidth: "none", left: pct(-box.cx / box.cw), top: pct(-box.cy / box.ch), width: pct(shot.width / box.cw), height: pct(shot.height / box.ch) }}
      />
      {vis === "ok" && rect && (
        <div
          aria-hidden="true"
          style={{ position: "absolute", left: pct((rect.x - box.cx) / box.cw), top: pct((rect.y - box.cy) / box.ch), width: pct(rect.w / box.cw), height: pct(rect.h / box.ch), boxShadow: "0 0 0 2px #fff, 0 0 0 5px #b00020", minWidth: 6, minHeight: 6 }}
        />
      )}
    </div>
  );
  return (
    <div className="flex flex-col gap-2">
      {vis === "hidden" && <p>This element is not visible on the page (it may be hidden or off-screen), so it cannot be outlined. The picture shows the top of the page.</p>}
      {vis === "below" && <p>This element is lower on the page than the part we saved{shot.truncated ? ` (the top ${shot.height} pixels of ${shot.page_height})` : ""}, so it cannot be outlined.</p>}
      {whole ? (
        // A scrollable area must be reachable by keyboard (WCAG 2.1.1), so this region is deliberately focusable.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        <div role="region" aria-label="Screenshot of the whole saved page, scrollable" tabIndex={0} className="max-h-[28rem] overflow-auto">{image}</div>
      ) : image}
      {vis === "ok" && <p className="text-sm">The outlined area is the element with the problem.</p>}
      {shot.truncated && <p className="text-sm">Only the top {shot.height} pixels of this page ({shot.page_height} tall) were saved.</p>}
    </div>
  );
}
