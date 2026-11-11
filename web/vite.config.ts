import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the dashboard runs on :5173 and the API on :8000.
// Requests to /api are passed through, so the browser sees one origin.
const api = process.env.PCDOCTOR_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": api } },
  preview: { proxy: { "/api": api } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
