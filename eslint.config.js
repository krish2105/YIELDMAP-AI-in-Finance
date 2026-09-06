import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "node_modules/**",
      "**/node_modules/**",
      ".venv/**",
      ".next/**",
      "web/.next/**",
      "**/dist/**",
      "coverage/**",
      "data/**",
      // Vendored from the dataviz reference implementation and run as-is. Linting a dependency's
      // source to this project's rules would mean editing it, and then it is no longer the
      // reference implementation.
      "scripts/validate_palette.js",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  {
    // Build and measurement scripts run under Node, not in a browser.
    files: ["scripts/**/*.{js,mjs}", "*.config.{js,mjs,ts}", "playwright.config.ts"],
    languageOptions: {
      globals: { console: "readonly", process: "readonly", __dirname: "readonly" },
    },
  },
);
