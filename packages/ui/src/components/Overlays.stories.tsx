import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "./Button";
import { Dialog, DialogTrigger } from "./Dialog";
import { Select } from "./Select";
import { TextField } from "./TextField";
import { notify, ToastProvider } from "./Toast";

const meta = { title: "Components/Overlays" } satisfies Meta;
export default meta;
type S = StoryObj;

export const NewScanDialog: S = {
  render: () => (
    <DialogTrigger>
      <Button>New scan</Button>
      <Dialog title="New scan">
        <TextField label="Website URL" type="url" />
        <Select label="Standard" defaultValue="wcag22" options={[{ id: "wcag22", label: "WCAG 2.2 AA" }, { id: "508", label: "Section 508" }]} />
      </Dialog>
    </DialogTrigger>
  ),
};

export const SelectField: S = {
  render: () => <Select label="Standard" options={[{ id: "wcag22", label: "WCAG 2.2 AA" }, { id: "eaa", label: "EU EAA (EN 301 549)" }]} />,
};
export const SelectWithError: S = {
  render: () => <Select label="Standard" error="Choose a standard." options={[{ id: "wcag22", label: "WCAG 2.2 AA" }]} />,
};

export const Toasts: S = {
  render: () => (
    <div className="flex gap-2">
      <Button onPress={() => notify({ title: "Scan started", kind: "info" })}>Info</Button>
      <Button onPress={() => notify({ title: "Report ready", description: "Your PDF passed validation.", kind: "success" })}>Success</Button>
      <Button onPress={() => notify({ title: "Scan failed", description: "The site blocked our crawler.", kind: "error" })}>Error</Button>
      <ToastProvider />
    </div>
  ),
};
