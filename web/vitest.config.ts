import { defineConfig } from "vitest/config";

// Default environment is plain node; component tests opt into jsdom per file with
// `// @vitest-environment jsdom`. The gate writes its own files to tests/__gate__/.
export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    environment: "node",
    testTimeout: 30_000,
  },
});
