import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "./Button";

const meta = { title: "Components/Button", component: Button, args: { children: "Run scan" } } satisfies Meta<typeof Button>;
export default meta;
type S = StoryObj<typeof meta>;

export const Primary: S = {};
export const Secondary: S = { args: { variant: "secondary" } };
export const Danger: S = { args: { variant: "danger", children: "Delete organisation" } };
export const Disabled: S = { args: { isDisabled: true } };
export const Pending: S = { args: { isPending: true, pendingLabel: "Starting scan" } };
