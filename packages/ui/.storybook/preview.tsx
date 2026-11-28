import type { Preview } from "@storybook/react-vite";
import "../src/styles.css";
import { ToastProvider } from "../src/index";

const preview: Preview = {
  globalTypes: {
    theme: {
      description: "Colour theme",
      toolbar: { title: "Theme", items: ["light", "dark"], dynamicTitle: true },
    },
  },
  initialGlobals: { theme: "light" },
  decorators: [
    (Story, ctx) => {
      document.documentElement.dataset.theme = ctx.globals.theme;
      return (
        <div className="p-6">
          <Story />
          <ToastProvider />
        </div>
      );
    },
  ],
  parameters: {
    // Every story is checked by axe; violations are errors, not warnings.
    a11y: { test: "error" },
    layout: "fullscreen",
  },
};
export default preview;
