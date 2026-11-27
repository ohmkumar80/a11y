import type { Meta, StoryObj } from "@storybook/react-vite";
import { TextField } from "./TextField";

const meta = { title: "Components/TextField", component: TextField, args: { label: "Email", autoComplete: "email", type: "email" } } satisfies Meta<typeof TextField>;
export default meta;
type S = StoryObj<typeof meta>;

export const Default: S = {};
export const WithDescription: S = { args: { description: "We send your scan reports here." } };
export const WithError: S = { args: { error: "Enter an email address in the format name@example.com." } };
export const Disabled: S = { args: { isDisabled: true } };
export const Password: S = { args: { label: "Password", type: "password", autoComplete: "current-password", description: "At least 12 characters. Pasting is fine." } };
