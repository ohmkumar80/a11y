"use client";

import type { ReactNode } from "react";
import { Tab, TabList, TabPanel, Tabs as AriaTabs, type Key } from "react-aria-components";

export interface TabItem {
  id: Key;
  label: string;
  content: ReactNode;
}

export function Tabs({ label, items, defaultSelectedKey }: { label: string; items: TabItem[]; defaultSelectedKey?: Key }) {
  return (
    <AriaTabs defaultSelectedKey={defaultSelectedKey ?? items[0]?.id} className="flex flex-col gap-3">
      <TabList aria-label={label} className="flex gap-1 border-b-2 border-border-subtle">
        {items.map((t) => (
          <Tab
            key={t.id}
            id={t.id}
            className="-mb-0.5 min-h-11 cursor-default rounded-t-lg border-b-4 border-transparent px-4 py-2 font-semibold text-fg-muted hover:bg-bg-subtle hover:text-fg data-[selected]:border-accent data-[selected]:bg-accent-subtle data-[selected]:text-accent"
          >
            {t.label}
          </Tab>
        ))}
      </TabList>
      {items.map((t) => (
        <TabPanel key={t.id} id={t.id} className="rounded-md pt-4">
          {t.content}
        </TabPanel>
      ))}
    </AriaTabs>
  );
}
