"use client";

import {
  Cell,
  Column,
  Row,
  Table as AriaTable,
  TableBody,
  TableHeader,
  type Key,
  type SortDescriptor,
} from "react-aria-components";

export interface TableColumn<T> {
  id: string;
  header: string;
  isRowHeader?: boolean;
  allowsSorting?: boolean;
  render: (row: T) => React.ReactNode;
}

export interface TableProps<T> {
  /** Accessible name for the table (also use a visible caption/heading nearby). */
  label: string;
  columns: TableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => Key;
  sortDescriptor?: SortDescriptor;
  onSortChange?: (d: SortDescriptor) => void;
  emptyText?: string;
}

/**
 * Real <table> semantics via React Aria (th scope, aria-sort on sortable headers, announced
 * sort changes). Paginate instead of infinite scroll (PROJECT_PLAN 2.4).
 */
export function Table<T extends object>({ label, columns, rows, rowKey, emptyText = "No results.", ...sort }: TableProps<T>) {
  return (
    // Wide tables scroll inside their own region (SC 1.4.10 exception for data tables) instead of
    // scrolling the whole page. `relative` makes it the containing block for visually-hidden (absolutely
    // positioned) text inside cells; without it that text escapes the scroller and widens the page.
    // The region is focusable so keyboard users can scroll it.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- scrollable regions MUST be focusable so keyboard users can scroll (axe: scrollable-region-focusable)
    <div role="region" aria-label={`${label} (scrollable)`} tabIndex={0} className="relative max-w-full overflow-x-auto rounded-xl border-2 border-border-subtle bg-bg">
    <AriaTable aria-label={label} sortDescriptor={sort.sortDescriptor} onSortChange={sort.onSortChange} className="w-full border-collapse text-left">
      <TableHeader>
        {columns.map((c) => (
          <Column
            key={c.id}
            id={c.id}
            isRowHeader={c.isRowHeader}
            allowsSorting={c.allowsSorting}
            className="min-h-11 border-b-2 border-border-subtle bg-bg-subtle px-4 py-3 text-sm font-semibold"
          >
            {({ sortDirection }) => (
              <span className="inline-flex items-center gap-1">
                {c.header}
                {c.allowsSorting && (
                  <span aria-hidden="true">{sortDirection === "ascending" ? "▲" : sortDirection === "descending" ? "▼" : "↕"}</span>
                )}
              </span>
            )}
          </Column>
        ))}
      </TableHeader>
      <TableBody renderEmptyState={() => <p className="p-4 text-fg-muted">{emptyText}</p>}>
        {rows.map((r) => (
          <Row key={rowKey(r)} id={rowKey(r)} columns={columns} className="border-b border-border-subtle last:border-b-0 hover:bg-bg-subtle">
            {columns.map((c) => (
              <Cell key={c.id} className="px-4 py-3 [overflow-wrap:anywhere]">{c.render(r)}</Cell>
            ))}
          </Row>
        ))}
      </TableBody>
    </AriaTable>
    </div>
  );
}
