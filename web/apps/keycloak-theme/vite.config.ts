import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { keycloakify } from "keycloakify/vite-plugin"
import { defineConfig } from "vitest/config"

// https://docs.keycloakify.dev: `pnpm build` is the plain Vite build; `pnpm build-keycloak-theme`
// packages it as a Keycloak theme JAR (needs Maven + JDK, see deploy/keycloak/Dockerfile).
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    keycloakify({
      themeName: "shd-shop",
      // Login theme only; the account console stays Keycloak's own.
      accountThemeImplementation: "none",
      // Keycloak 26.x only: skip the JAR for Keycloak 22-25.
      keycloakVersionTargets: {
        "22-to-25": false,
        "all-other-versions": true,
      },
    }),
  ],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
})
