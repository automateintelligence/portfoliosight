import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The /api proxy exists only for `vite preview` during local Playwright runs: the page's
// same-origin /api/* calls go to the local mock (mock/server.mjs) and never leave localhost.
const MOCK_PORT = Number(process.env.PS_MOCK_PORT || 8791);

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false, target: "es2022" },
  preview: {
    proxy: {
      "/api": { target: `http://127.0.0.1:${MOCK_PORT}`, changeOrigin: false },
      "/__mock": { target: `http://127.0.0.1:${MOCK_PORT}`, changeOrigin: false },
    },
  },
});
