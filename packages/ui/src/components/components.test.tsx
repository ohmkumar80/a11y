import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { Button, Checkbox, Dialog, DialogTrigger, ErrorSummary, Link, Meter, ProgressBar, Select, Table, Tabs, TextField } from "../index";

describe("Button", () => {
  it("has no axe violations and fires on keyboard Enter and Space", async () => {
    const onPress = vi.fn();
    const { container } = render(<Button onPress={onPress}>Save</Button>);
    expect(await axe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole("button", { name: "Save" })).toHaveFocus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(onPress).toHaveBeenCalledTimes(2);
  });

  it("announces the pending state to screen readers", () => {
    render(<Button isPending pendingLabel="Saving">Save</Button>);
    expect(screen.getByRole("button")).toHaveTextContent("Saving");
  });
});

describe("TextField", () => {
  it("links label, description and error to the input", async () => {
    const { container } = render(
      <TextField label="Email" description="We never share it" error="Enter a valid email address." type="email" autoComplete="email" />,
    );
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAccessibleDescription(/We never share it/);
    expect(input).toHaveAccessibleDescription(/Enter a valid email address\./);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("autocomplete", "email");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("allows paste (SC 3.3.8)", async () => {
    render(<TextField label="Password" type="password" autoComplete="current-password" />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Password"));
    await user.paste("pasted-from-password-manager");
    expect(screen.getByLabelText("Password")).toHaveValue("pasted-from-password-manager");
  });
});

describe("Dialog", () => {
  it("traps focus, closes on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(
      <DialogTrigger>
        <Button>New scan</Button>
        <Dialog title="New scan">
          <TextField label="URL" />
        </Dialog>
      </DialogTrigger>,
    );
    const trigger = screen.getByRole("button", { name: "New scan" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "New scan" });
    // Initial focus lands inside the dialog (on the dialog itself, which is named by its title).
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(within(dialog).getByLabelText("URL")).toBeInTheDocument();
    await user.tab(); await user.tab(); await user.tab();
    expect(dialog).toContainElement(document.activeElement as HTMLElement); // never leaves
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Focus is restored asynchronously after the dialog unmounts.
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

describe("Select", () => {
  it("opens with the keyboard and selects with Enter", async () => {
    const onChange = vi.fn();
    render(<Select label="Standard" options={[{ id: "wcag22", label: "WCAG 2.2 AA" }, { id: "508", label: "Section 508" }]} onChange={onChange} />);
    const user = userEvent.setup();
    await user.tab();
    await user.keyboard("{Enter}");
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalled();
  });
});

describe("Tabs", () => {
  it("moves between tabs with arrow keys", async () => {
    const { container } = render(
      <Tabs label="Views" items={[{ id: "a", label: "Issues", content: <p>A</p> }, { id: "b", label: "Reports", content: <p>B</p> }]} />,
    );
    expect(await axe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.tab();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Reports" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("Meter / ProgressBar", () => {
  it("exposes role=meter with a spoken value", async () => {
    const { container } = render(<Meter label="Seats" value={7} maxValue={10} valueText="7 of 10 seats used" />);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuetext", "7 of 10 seats used");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("flags near-full meters with text, not only colour", () => {
    render(<Meter label="Scans" value={9} maxValue={10} valueText="9 of 10 scans used" />);
    expect(screen.getByText(/nearly full/)).toBeInTheDocument();
  });

  it("progress bar is role=progressbar", async () => {
    const { container } = render(<ProgressBar label="Scan progress" value={50} valueText="50%" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("Table", () => {
  it("renders a real grid with column headers and sort state", async () => {
    const rows = [{ id: 1, name: "Acme" }, { id: 2, name: "Globex" }];
    const { container } = render(
      <Table label="Tenants" rows={rows} rowKey={(r) => r.id} sortDescriptor={{ column: "name", direction: "ascending" }}
        columns={[{ id: "name", header: "Name", isRowHeader: true, allowsSorting: true, render: (r) => r.name }]} />,
    );
    expect(screen.getByRole("columnheader", { name: /Name/ })).toHaveAttribute("aria-sort", "ascending");
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("Link and ErrorSummary", () => {
  it("link has no violations", async () => {
    const { container } = render(<Link href="/help">Help</Link>);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("error summary takes focus and links to the field", async () => {
    const { container } = render(
      <>
        <ErrorSummary errors={[{ fieldId: "email", message: "Enter an email" }]} />
        <input id="email" aria-label="Email" />
      </>,
    );
    expect(screen.getByRole("alert")).toHaveFocus();
    await userEvent.setup().click(screen.getByRole("link", { name: "Enter an email" }));
    expect(screen.getByLabelText("Email")).toHaveFocus();
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("Checkbox", () => {
  it("is a named checkbox, toggles with Space and has no axe violations", async () => {
    const onChange = vi.fn();
    const { container } = render(<Checkbox label="Enabled" onChange={onChange} />);
    expect(await axe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.tab();
    const box = screen.getByRole("checkbox", { name: "Enabled" });
    expect(box).toHaveFocus();
    await user.keyboard(" ");
    expect(onChange).toHaveBeenCalledWith(true);
    expect(box).toBeChecked();
  });
});
