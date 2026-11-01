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
    // `pnpm dev`: same-origin /api like behind the gateway. Default: a local Status API
    // (`uv run status-api`), because status.localtest.me requires single sign-on since Phase 6.
    proxy: {
      "/api": {
        target: process.env.STATUS_API_URL ?? "http://localhost:8080",
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
