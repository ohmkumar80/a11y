import type { Meta, StoryObj } from "@storybook/react-vite";
import { Meter, ProgressBar } from "./Meter";
import { Table } from "./Table";
import { Tabs } from "./Tabs";

const meta = { title: "Components/Data display" } satisfies Meta;
export default meta;
type S = StoryObj;

export const SeatMeter: S = { render: () => <Meter label="Seats" value={7} maxValue={10} valueText="7 of 10 seats used" /> };
export const SeatMeterNearlyFull: S = { render: () => <Meter label="Seats" value={10} maxValue={10} valueText="10 of 10 seats used" /> };
export const ScanProgress: S = { render: () => <ProgressBar label="Scan progress" value={50} valueText="50%" /> };
export const ScanProgressIndeterminate: S = { render: () => <ProgressBar label="Scan progress" /> };

export const FindingsTable: S = {
  render: () => (
    <Table
      label="Findings"
      rows={[{ id: 1, rule: "Image missing alt text", sc: "1.1.1", count: 12 }, { id: 2, rule: "Insufficient contrast", sc: "1.4.3", count: 4 }]}
      rowKey={(r) => r.id}
      columns={[
        { id: "rule", header: "Issue", isRowHeader: true, allowsSorting: true, render: (r) => r.rule },
        { id: "sc", header: "WCAG", render: (r) => r.sc },
        { id: "count", header: "Instances", allowsSorting: true, render: (r) => r.count },
      ]}
    />
  ),
};
export const EmptyTable: S = { render: () => <Table label="Findings" rows={[]} rowKey={() => 0} columns={[{ id: "a", header: "Issue", isRowHeader: true, render: () => null }]} emptyText="No findings yet. Run a scan." /> };

export const TabsExample: S = {
  render: () => <Tabs label="Results views" items={[{ id: "issues", label: "Issues", content: <p>Issue list</p> }, { id: "pages", label: "Pages", content: <p>Page list</p> }]} />,
};
