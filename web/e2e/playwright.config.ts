import { defineConfig, devices } from "@playwright/test"

// Browser flows against the running kind cluster (`make verify-browser`). Chromium resolves every
// *.localtest.me host to the gateway on 127.0.0.1 itself, independent of the host's DNS resolver.
// TLS: the mkcert CA is checked by `make verify` (curl --cacert); here the browser does not need it
// in a trust store.
export default defineConfig({
  testDir: ".",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  outputDir: "../../.cache/e2e-results",
  use: {
    ...devices["Desktop Chrome"],
    viewport: { width: 1280, height: 900 },
    ignoreHTTPSErrors: true,
    launchOptions: {
      args: ["--host-resolver-rules=MAP *.localtest.me 127.0.0.1"],
    },
    trace: "retain-on-failure",
  },
})
