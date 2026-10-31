# Web frontends (pnpm monorepo)

React, TypeScript, Vite, Tailwind CSS and [shadcn/ui](https://ui.shadcn.com/docs/installation/vite).
Scaffolded with the official CLI, `shadcn@4.23.0 init -t vite --monorepo -b radix -p nova`, and built with turbo.

| Path | What |
|---|---|
| `apps/status` | Status page (Phase 4) on http://status.localtest.me |
| `apps/shop` | Customer shop page (Phase 6, not built yet) |
| `packages/ui` (`@workspace/ui`) | Shared shadcn/ui components (Card, Badge, Table, Alert, Tooltip, Chart, Skeleton, Button), styles and `cn` |

## Status page

![Status page during a latency fault on User](../docs/screenshots/status-page.png)

- Polls `GET /api/v1/services` and `GET /api/v1/alerts` every 10 s (TanStack Query), on the **same origin**: the gateway routes
  `/api` on `status.localtest.me` to the Status API, so there is no CORS and no API URL in the bundle. The contract is in
  [services/README.md](../services/README.md#status-api).
- One card per service: status badge (icon + word, not colour alone), reasons, RPS / 5xx % / p95 with 30-minute sparklines
  (shadcn Charts on Recharts; dashed line = alert threshold), ready replicas and probe, and a link to its Grafana Service Detail
  dashboard. An overall banner (`aria-live`), an active-alerts table, and warnings when the API or one of its sources is unreachable
  (the last answer stays visible).
- Dark mode: follows the system, toggle in the header (or press `d`).

## Development

Node ≥ 20.19 and pnpm 12 (`brew install pnpm`, or `npm i -g pnpm@12`).

```bash
make web-check        # pnpm install --frozen-lockfile, Prettier check, ESLint, tsc, Vitest, vite build
make web-dev          # dev server; /api is proxied to STATUS_API_URL (default http://status.localtest.me)
STATUS_API_URL=http://localhost:8080 make web-dev   # against `uv run status-api`
```

Add shadcn components from `web/`: `pnpm dlx shadcn@latest add <component> -c apps/status` (they land in `packages/ui`).
If the CLI fails with `unable to get local issuer certificate` (Node's bundled CA store vs. your network), run it with
`NODE_EXTRA_CA_CERTS=/etc/ssl/cert.pem` (macOS system CAs).

## Image

[`Dockerfile`](Dockerfile) (context `web/`, `--build-arg APP=status`): pnpm install and `vite build` on `node:24-slim`, then the
static files on `nginxinc/nginx-unprivileged` (UID 101, port 8080, ~63 MB). [`nginx.conf`](nginx.conf): SPA fallback, immutable
caching for hashed `/assets`, `no-cache` for `index.html`, security headers (CSP, `nosniff`, `frame-ancestors 'none'`), `/livez`
and `/readyz`. It runs with a read-only root filesystem; only `/tmp` (emptyDir) is writable. `make images` builds and loads it.
