import "@testing-library/jest-dom/vitest"
import { cleanup } from "@testing-library/react"
import { afterEach, vi } from "vitest"

afterEach(() => {
  cleanup()
})

// Keycloakify's Template initialisation injects Keycloak's scripts and reloads the page when the
// Template mounts twice (it emulates a server-rendered page); neither makes sense in jsdom.
vi.mock("keycloakify/login/Template.useInitialize", () => ({
  useInitialize: () => ({ isReadyToRender: true }),
}))
