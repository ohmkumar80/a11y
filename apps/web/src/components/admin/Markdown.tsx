"use client";

import { Fragment } from "react";
import { inline } from "@/lib/openapi";

function Inline({ text }: { text: string }) {
  return (
    <>
      {inline(text).map((t, i) =>
        t.kind === "code" ? <code key={i}>{t.value}</code>
        : t.kind === "bold" ? <strong key={i}>{t.value}</strong>
        : t.kind === "link" ? <a key={i} href={t.href} className="underline" rel="noopener noreferrer">{t.value}</a>
        : <Fragment key={i}>{t.value}</Fragment>,
      )}
    </>
  );
}

/** The small subset of Markdown our own runbooks use: headings (`#`, `##`), numbered and bullet lists, paragraphs, `code`
 *  and **bold**. Nothing is ever interpreted as HTML. `base` is the heading level of the first `#`. */
export function Markdown({ source, base = 3 }: { source: string; base?: number }) {
  const blocks: React.ReactNode[] = [];
  const lines = source.split("\n");
  let para: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flushPara = () => { if (para.length) { blocks.push(<p key={blocks.length}><Inline text={para.join(" ")} /></p>); para = []; } };
  const flushList = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(<Tag key={blocks.length} className={list.ordered ? "list-decimal pl-6" : "list-disc pl-6"}>{list.items.map((t, i) => <li key={i}><Inline text={t} /></li>)}</Tag>);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    const num = /^\d+\.\s+(.*)$/.exec(line);
    const bul = /^[-*]\s+(.*)$/.exec(line);
    const cont = /^\s{2,}\S/.test(raw) && list; // an indented continuation of the previous list item
    if (h) {
      flushPara(); flushList();
      const level = Math.min(6, base + (h[1]!.length - 1));
      const Tag = `h${level}` as "h3";
      blocks.push(<Tag key={blocks.length} className={level <= base ? "text-lg font-bold" : "text-base font-semibold"}><Inline text={h[2]!} /></Tag>);
    } else if (num || bul) {
      flushPara();
      const ordered = !!num;
      if (!list || list.ordered !== ordered) { flushList(); list = { ordered, items: [] }; }
      list.items.push((num ?? bul)![1]!);
    } else if (cont && list) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else if (line.trim() === "") {
      flushPara(); flushList();
    } else {
      flushList(); para.push(line.trim());
    }
  }
  flushPara(); flushList();
  return <div className="flex max-w-prose flex-col gap-2">{blocks}</div>;
}
