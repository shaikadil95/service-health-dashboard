# Service Health Dashboard

A **lightweight observability solution** for three backend services (User, Order and Payment). It shows how R&D teams can:

1. **Collect** health and performance data: metrics, logs, traces and probe status
2. **Visualize** the current status of each service
3. **Detect** problems such as high error rates, slow responses or a service that is down
4. **Notify** an on-call engineer when a critical condition occurs

It is an architecture exercise that focuses on **design decisions and trade-offs**. It is also a demo you can reproduce on a laptop:
`make up` → break a service → see red status → receive an email.

> **Status: Phase 0 (design).** This repository contains the design documents only. Code arrives phase by phase. See the [roadmap](docs/roadmap.md).

## Documentation

| Document | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | **The main deliverable.** Goals, the architecture, the five main data flows, trade-offs, probe design, alerting, the Status API contract, networking, security, and how the design evolves for production |
| [Architecture Decision Records](docs/adr/README.md) | One MADR document for each key decision (ADRs 0001–0010) |
| [Diagrams](docs/diagrams/) | Mermaid sources (`.mmd`) and rendered SVG files |
| [Roadmap](docs/roadmap.md) | Phases 0–7 with scope and exit criteria |
| [CI/CD placeholder](.github/workflows/README.md) | Planned CI and GitOps CD |

## Architecture overview

```mermaid
flowchart LR
  client(["Browser / k6"])
  gw["Envoy Gateway<br/>*.localtest.me"]

  subgraph apps["apps namespace"]
    user["User svc"]
    order["Order svc"]
    pay["Payment svc"]
  end

  subgraph obs["observability namespace"]
    otel["OTel Collector<br/>DaemonSet"]
    prom["Prometheus"]
    loki["Loki"]
    tempo["Tempo"]
    am["Alertmanager"]
    graf["Grafana"]
    sapi["Status API<br/>+ status page"]
    mail(["Mailpit inbox<br/>on-call"])
    bb["Blackbox<br/>exporter"]
  end

  client --> gw
  gw --> order & user & pay
  order --> user
  order --> pay
  gw --> graf & sapi

  apps -. "OTLP traces + metrics,<br/>stdout logs" .-> otel
  otel --> prom & loki & tempo
  tempo -- "span metrics" --> prom
  prom -- "alerts" --> am
  am -- "SMTP" --> mail
  prom -- "scrape" --> bb
  bb -. "probe /readyz" .-> apps

  graf --> prom & loki & tempo
  sapi --> prom & am
```

The services send traces and metrics over OTLP to a node-local OpenTelemetry Collector and write JSON logs to stdout.
The Collector fans the data out to Prometheus, Loki and Tempo. Prometheus also scrapes cluster health data and blackbox probes,
and evaluates the alerting rules. Alertmanager emails the on-call engineer, through Mailpit locally. Grafana is the tool engineers use to investigate,
and the Status API and status page give everyone else a simple UP, DEGRADED or DOWN view.
The [architecture document](docs/architecture.md) explains each flow.

## Tech stack

| Concern | Choice | ADR |
|---|---|---|
| Services | Python 3.12, FastAPI | — |
| Instrumentation | OpenTelemetry SDK (OTLP) | [0001](docs/adr/0001-opentelemetry-for-instrumentation.md) |
| Collection | OpenTelemetry Collector (contrib) as a DaemonSet | [0002](docs/adr/0002-collector-topology.md) |
| Traces | Grafana Tempo with the metrics-generator | [0003](docs/adr/0003-tempo-vs-jaeger.md) |
| Metrics | Prometheus (kube-prometheus-stack): OTLP push and scrape, kube-state-metrics, blackbox exporter | [0004](docs/adr/0004-prometheus-otlp-push-and-scrape.md) |
| Logs | Grafana Loki | [0005](docs/adr/0005-loki-for-logs.md) |
| Dashboards | Grafana (dashboards as code) | [0004](docs/adr/0004-prometheus-otlp-push-and-scrape.md) |
| Status view | Status API (FastAPI backend for frontend) and a status page in React, TypeScript, Vite, Tailwind and shadcn/ui | [0006](docs/adr/0006-status-api-bff-and-status-page.md) |
| Alerting | Prometheus rules → Alertmanager → email (Mailpit) | [0007](docs/adr/0007-alertmanager-routing-and-mailpit.md) |
| Edge | Envoy Gateway (Kubernetes Gateway API) on `*.localtest.me` | [0008](docs/adr/0008-envoy-gateway-as-edge.md) |
| Identity (Phase 6) | Keycloak (`customers` and `ops` realms), Envoy Gateway OIDC and JWT | [0009](docs/adr/0009-keycloak-and-sso.md) |
| Runtime and deployment | kind on Docker or Podman, Helm 4, helmfile, Makefile | [0010](docs/adr/0010-local-runtime-kind.md) |
| Load | k6 | — |

## Roadmap

| Phase | Scope | Exit criteria |
|---|---|---|
| **0** Foundations | Architecture document, ADRs, diagrams, repository setup | The design can be reviewed as the interview deliverable |
| **1** Services | FastAPI services, OTel, probes, fault injection, tests, compose | Tests pass. One order produces one distributed trace. |
| **2** Platform | kind, Makefile, Helm chart, Envoy Gateway, CoreDNS rewrite, NetworkPolicies | `make up`. `api.localtest.me` works from the host and from a pod. Readiness behaviour verified. |
| **3** Telemetry | Collector, Prometheus, Loki, Tempo, blackbox exporter, k6 | All three signals can be queried in Grafana, and the service graph is visible |
| **4** Visualization | Grafana dashboards and links between signals, Status API, shadcn/ui status page | An injected fault is visible within about one minute |
| **5** Alerting | Rules, Alertmanager to Mailpit, runbooks, `demo.sh` | Every failure scenario turns the status red and delivers an email |
| **6** Identity | Keycloak, HTTPS, OIDC and JWT, customer shop page | Customer login and order. SSO for engineers. `401` without a token. |
| **7** CI/CD | Placeholder: GitHub Actions CI and Argo CD | — |

Full details are in [docs/roadmap.md](docs/roadmap.md).

## Local URLs

These are available **from Phase 2 onwards**. Each URL appears in the phase that adds its component. `*.localtest.me` resolves to `127.0.0.1` through public DNS.

| URL | What | From phase |
|---|---|---|
| http://api.localtest.me | User, Order and Payment APIs | 2 |
| http://grafana.localtest.me | Grafana | 3 |
| http://prometheus.localtest.me | Prometheus | 3 |
| http://alertmanager.localtest.me | Alertmanager | 3 |
| http://status.localtest.me | Status page and Status API (`/api`) | 4 |
| http://mail.localtest.me | Mailpit (on-call inbox) | 5 |
| https://sso.localtest.me | Keycloak | 6 |
| https://shop.localtest.me | Customer shop page | 6 |

From Phase 6, every URL uses HTTPS.

## Prerequisites

- **Docker** (preferred), or **Podman** with a rootful machine of at least 4 CPUs and 8 GB of memory (kind's Podman provider is experimental)
- [kind](https://kind.sigs.k8s.io/) **0.33 or later**
- [kubectl](https://kubernetes.io/docs/tasks/tools/), within the supported version skew of the kind node image
- [Helm](https://helm.sh/) **4**
- [helmfile](https://helmfile.readthedocs.io/) and the [helm-diff](https://github.com/databus23/helm-diff) plugin
- Later phases: [k6](https://grafana.com/docs/k6/latest/) (Phase 3), [pnpm](https://pnpm.io/) and Node.js for frontend development (Phase 4), [mkcert](https://github.com/FiloSottile/mkcert) (Phase 6)

## Getting started

**Coming in Phase 2.** The planned flow is `make up` to create the cluster and deploy everything, `scripts/demo.sh` to run the failure scenarios, and `make down` to remove it all.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The project uses Conventional Commits and one pull request per phase.

## License

[MIT](LICENSE)
