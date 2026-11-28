import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: [".next", "node_modules", "next-env.d.ts", "playwright-report", "test-results"] },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "jsx-a11y": jsxA11y },
    rules: { ...jsxA11y.flatConfigs.strict.rules },
    languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
  },
);
