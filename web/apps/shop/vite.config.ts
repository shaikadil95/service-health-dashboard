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
    // `pnpm dev`: same-origin /api like behind the gateway, proxied to a local Order service
    // (`AUTH_ENABLED=false uv run order-service`); /api/me needs the gateway's session.
    proxy: {
      "/api/orders": {
        target: process.env.ORDER_API_URL ?? "http://localhost:8082",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
})
