import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        raised: "var(--bg-raised)",
        sunken: "var(--bg-sunken)",
        ink: "var(--ink)",
        "ink-secondary": "var(--ink-secondary)",
        "ink-muted": "var(--ink-muted)",
        line: "var(--line)",
        "line-strong": "var(--line-strong)",
        teal: "var(--teal)",
        "teal-ink": "var(--teal-ink)",
        sand: "var(--sand)",
        "warn-ink": "var(--warn-ink)",
      },
      fontFamily: {
        display: "var(--font-display)",
        sans: "var(--font-sans)",
        mono: "var(--font-mono)",
      },
      fontSize: {
        xs: "var(--step--1)",
        base: "var(--step-0)",
        lg: "var(--step-1)",
        xl: "var(--step-2)",
        "2xl": "var(--step-3)",
        "3xl": "var(--step-4)",
        hero: "var(--step-hero)",
      },
      boxShadow: { card: "var(--shadow)" },
      transitionTimingFunction: {
        "out-expo": "var(--ease-out-expo)",
        "out-quart": "var(--ease-out-quart)",
      },
    },
  },
  plugins: [],
};

export default config;
