import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["storybook-static", "dist"] },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "jsx-a11y": jsxA11y },
    // strict = every rule at "error"
    rules: { ...jsxA11y.flatConfigs.strict.rules },
    languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
  },
);
