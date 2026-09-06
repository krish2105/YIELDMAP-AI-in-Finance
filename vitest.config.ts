import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: ["web/**/*.test.ts", "web/**/*.test.tsx"],
  },
});
