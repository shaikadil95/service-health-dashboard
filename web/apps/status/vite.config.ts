import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // `pnpm dev`: same-origin /api like behind the gateway, e.g.
    // STATUS_API_URL=http://localhost:8080 (uv run status-api) or http://status.localtest.me
    proxy: {
      "/api": {
        target: process.env.STATUS_API_URL ?? "http://status.localtest.me",
        changeOrigin: true,
      },
    },
  },
  build: {
    // Recharts and Radix make one ~210 kB (gzip) bundle; fine for an internal status page.
    chunkSizeWarningLimit: 800,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
})
