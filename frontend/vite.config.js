import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({ plugins: [react()],
  test: {
    setupFiles: ["./src/test-setup.js"], environment: "jsdom" }, server: { proxy: { "/api": "http://127.0.0.1:8000" } } });
