# Architecture: Service Health Dashboard

> A lightweight observability solution for three backend services (User, Order, Payment).
> This document is the design deliverable: the architecture, the main data flows and the reasoning behind each
> decision, with the alternatives that were considered and the trade-offs that were accepted (see [§5](#5-key-decisions-and-trade-offs)).

## Contents

1. [Problem, goals and non-goals](#1-problem-goals-and-non-goals)
2. [Architecture overview](#2-architecture-overview)
3. [Component responsibilities](#3-component-responsibilities)
4. [Main data flows](#4-main-data-flows)
5. [Key decisions and trade-offs](#5-key-decisions-and-trade-offs)
6. [Health probe design](#6-health-probe-design)
7. [Detection and alerting strategy](#7-detection-and-alerting-strategy)
8. [Status API contract](#8-status-api-contract)
9. [Networking](#9-networking)
10. [Security and identity](#10-security-and-identity)
11. [Evolving to production](#11-evolving-to-production)
12. [Risks and mitigations](#12-risks-and-mitigations)
13. [References](#13-references)

---

## 1. Problem, goals and non-goals

**Brief:** design a lightweight observability solution for three backend services (User, Order and
Payment) that helps R&D teams to:

| # | Requirement | How this design meets it |
|---|---|---|
| R1 | Collect health and performance data | The OpenTelemetry SDK in each service sends traces, metrics and logs through an OpenTelemetry Collector. Prometheus scrapes Kubernetes and node health data. |
| R2 | Show the current status of each service | A **Status API** (backend for frontend) and a status page built with React and shadcn/ui show UP, DEGRADED or DOWN for each service. Grafana dashboards show the RED metrics (rate, errors, duration) and give a path from a metric to its traces and logs. |
| R3 | Detect problems such as high error rates or slow responses | Prometheus alerting rules watch the error ratio, p95 latency, black-box availability, pod readiness and the telemetry pipeline itself. The paging alerts are symptom-based. |
| R4 | Notify an on-call engineer when a critical condition occurs | Alertmanager groups, deduplicates, inhibits and routes alerts by severity, then sends email. Locally, Mailpit catches the email. |

**Goals**

- Use open standards and avoid vendor lock-in. Instrument once with OpenTelemetry (OTLP) and keep the backends replaceable.
- Keep it **lightweight**. The whole stack runs on a laptop in a `kind` cluster and installs with one command (`make up`, from Phase 2).
- Correlate the three signals. A metric spike links to an exemplar trace, and the trace links to its logs.
- Run every component as it would run in production, so the system can grow (see [§11](#11-evolving-to-production)).
- Write down the trade-offs so reviewers can challenge each decision.

**Non-goals (for this exercise)**

- High availability, multi-cluster deployment and long-term retention. These are covered on paper in §11 but not built.
- Real paging integrations such as PagerDuty or Opsgenie. Mailpit stands in for them, and the receiver can be swapped by changing configuration.
- Real business logic, persistence or payment processing. The services are small FastAPI apps with in-memory stores and a fault-injection endpoint (`/admin/faults`: error rate, added latency, not-ready), so that failures can be demonstrated. Because there is no database, traces contain no DB spans.
- A working CI/CD pipeline. It is planned as GitHub Actions CI and Argo CD GitOps (see [§11](#11-evolving-to-production)).

## 2. Architecture overview

![Architecture overview](diagrams/overview.svg)

<details>
<summary>Mermaid source (<a href="diagrams/overview.mmd">overview.mmd</a>)</summary>

```mermaid
flowchart LR
  client(["Browser / k6"])
  gw["Envoy Gateway<br/>*.localtest.me (HTTPS, SSO)"]
  kc["Keycloak<br/>identity namespace"]

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
  gw -- "OIDC / JWT" --> kc
  gw --> order & user
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

</details>

**In one paragraph:** the services are instrumented with the OpenTelemetry SDK. They send traces and
metrics over OTLP to a node-local OpenTelemetry Collector, and they write structured JSON logs to stdout,
which the same Collector reads from the node. The Collector enriches each signal with Kubernetes metadata
and fans it out: metrics go to **Prometheus**, logs go to **Loki** and traces go to **Tempo**. Tempo's
metrics-generator derives span metrics and a service graph and writes them back to Prometheus. Prometheus also
**scrapes** cluster health data (kube-state-metrics, kubelet and node-exporter) and a **blackbox exporter** that
probes each service's `/readyz` from outside, and it evaluates alerting rules. **Alertmanager** routes firing alerts
to email (**Mailpit** locally). **Grafana** is the analysis UI for engineers. The **Status API** reduces Prometheus
and Alertmanager data to a simple per-service status, which a React and shadcn/ui **status page** displays.
**Envoy Gateway**, which implements the Kubernetes Gateway API, is the single entry point on `*.localtest.me`.
A k6 load generator sends steady traffic so that there is always something to observe.

## 3. Component responsibilities

| Component | Responsibility | Deployed as (local) |
|---|---|---|
| User / Order / Payment services | Business APIs in Python 3.12 and FastAPI: User `GET /users/{id}`, Order `POST /orders` and `GET /orders/{id}`, Payment `POST /payments`. Order calls User and Payment. They expose `/livez`, `/readyz` and `/admin/faults`, send OTLP telemetry including business metrics (`orders_created_total`, `payments_processed_total{result}`), and write JSON logs to stdout. | Deployment per service |
| OpenTelemetry SDK | Auto- and manual instrumentation. Propagates W3C Trace Context and uses the HTTP semantic conventions. | Library in each service |
| OpenTelemetry Collector | Receives OTLP data and tails pod logs (`filelog`). Applies `memory_limiter`, `k8sattributes` and `batch`, then exports to the backends. | DaemonSet (agent) |
| Prometheus (kube-prometheus-stack) | Metrics storage. Native OTLP receiver and remote-write receiver. Scrapes cluster targets and evaluates recording and alerting rules. | StatefulSet (Prometheus Operator) |
| kube-state-metrics, node-exporter | Kubernetes object state (replicas, readiness, restarts) and node resources | Part of kube-prometheus-stack |
| Blackbox exporter | Synthetic HTTP checks of each service's `/readyz`. `probe_success` is the basis of `ServiceDown`. | Deployment |
| Loki | Log storage. Indexes labels only and accepts OTLP log ingestion. | Single-binary mode |
| Tempo | Trace storage, TraceQL queries, and a metrics-generator for span metrics and the service graph | Single-binary mode |
| Alertmanager | Grouping, deduplication, inhibition, silences and severity-based routing | Part of kube-prometheus-stack |
| Mailpit | Local SMTP sink with a web UI. Stands in for the on-call notification channel. | Deployment |
| Grafana | Dashboards as code (Service Health Overview, Service Detail), Explore, Traces Drilldown, and links between signals (exemplars to traces to logs). Keycloak login with group-based roles. | Part of kube-prometheus-stack |
| Status API | FastAPI backend for frontend, itself instrumented with OTel. Queries Prometheus and Alertmanager and computes each service's status. | Deployment |
| Web frontends | React, TypeScript, Vite, Tailwind and shadcn/ui in a pnpm monorepo under `web/`: `apps/status` (status page, Phase 4), `apps/shop` (customer page, Phase 6) and the shared `packages/ui` (`@workspace/ui`). Built as static assets. | `nginx-unprivileged` Deployment per app |
| k6 | Steady, low background traffic for the demo | Deployment ([`loadgen/`](../loadgen)) |
| Envoy Gateway | Gateway API implementation. Host-based routing on `*.localtest.me`, TLS termination, OIDC login with a gateway-managed session, JWT validation and claim-based authorization (`SecurityPolicy`). | Deployment and managed Envoy proxy |
| cert-manager | Issues and renews the `*.localtest.me` certificate of the Gateway from a CA issuer backed by the mkcert local CA | Deployment (official chart) |
| Keycloak | Identity provider at `sso.localtest.me`. A `customers` realm for the shop and API, and an `ops` realm for operations UIs. Realms, clients, roles and groups as code. | Official **Keycloak Operator** (`Keycloak` and `KeycloakRealmImport` CRs) with a plain PostgreSQL StatefulSet (official image, PVC) |
| kind on Podman or Docker | Local Kubernetes runtime | Containers on the host |

### Custom resources (CRDs)

The design uses **only vendor CRDs** and defines **none of its own**. This keeps the API surface small and puts upgrades in upstream hands.

| Provider | CRDs used | From phase |
|---|---|---|
| Gateway API (upstream, installed with Envoy Gateway) | `GatewayClass`, `Gateway`, `HTTPRoute` | 2 |
| Envoy Gateway | `EnvoyProxy` (proxy telemetry and NodePorts), `SecurityPolicy` (OIDC and JWT) | 2, 6 |
| Prometheus Operator (kube-prometheus-stack) | `Prometheus`, `Alertmanager`, `ServiceMonitor`, `PodMonitor`, `Probe`, `PrometheusRule`, `AlertmanagerConfig` | 3, 5 |
| cert-manager | `ClusterIssuer`, `Certificate` | 6 |
| Keycloak Operator | `Keycloak`, `KeycloakRealmImport` | 6 |

**Not used on purpose:**
- **OpenTelemetry Operator.** We do not use auto-instrumentation injection, because the services instrument themselves with the SDK. One Collector
  DaemonSet is easier to manage with the Helm chart than through `OpenTelemetryCollector` resources and the operator's admission webhooks.
- **Grafana Operator.** kube-prometheus-stack's Grafana sidecar already provisions datasources and dashboards from labelled ConfigMaps, which is enough for dashboards as code.

**CRD lifecycle.** Helm installs CRDs from a chart's `crds/` directory on the first install only. It [never upgrades or deletes them][helm-crds].
helmfile therefore installs the CRDs first, as separate releases ordered with `needs:`, before the releases that use them. The large
Prometheus Operator CRDs are applied with **server-side apply**, because client-side `kubectl apply` would exceed the 256 KiB limit on the
`last-applied-configuration` annotation.

## 4. Main data flows

![Telemetry data flow](diagrams/telemetry-flow.svg)

<details>
<summary>Mermaid source (<a href="diagrams/telemetry-flow.mmd">telemetry-flow.mmd</a>)</summary>

```mermaid
flowchart LR
  svc["FastAPI service<br/>OTel SDK"]
  stdout["Container stdout<br/>JSON logs + trace_id"]

  subgraph col["OTel Collector (DaemonSet, one per node)"]
    rotlp["otlp receiver<br/>:4317 / :4318"]
    rfile["filelog receiver<br/>/var/log/pods"]
    proc["memory_limiter<br/>k8sattributes<br/>batch"]
  end

  subgraph backends["Storage backends"]
    prom["Prometheus<br/>OTLP + remote-write receivers"]
    loki["Loki"]
    tempo["Tempo"]
    mg["Tempo<br/>metrics-generator"]
  end

  ksm["kube-state-metrics"]
  bb["blackbox exporter"]
  nodeexp["node-exporter<br/>kubelet / cAdvisor"]
  graf["Grafana"]

  svc -- "OTLP: traces + metrics" --> rotlp
  svc -- "writes" --> stdout
  stdout -- "tail" --> rfile
  rotlp --> proc
  rfile --> proc
  proc -- "OTLP metrics" --> prom
  proc -- "OTLP logs" --> loki
  proc -- "OTLP traces" --> tempo
  tempo --> mg
  mg -- "remote_write:<br/>span metrics, service graph" --> prom
  prom -- "scrape" --> ksm
  prom -- "scrape" --> nodeexp
  prom -- "scrape" --> bb
  bb -. "HTTP probe /readyz" .-> svc
  graf -- "PromQL / LogQL / TraceQL" --> backends
```

</details>

### Flow 1: Telemetry push (application to backends)

1. Each service runs the OpenTelemetry Python SDK with FastAPI, `httpx` and logging instrumentation. Spans and
   metrics (for example the `http.server.request.duration` histogram from the HTTP semantic conventions) go over **OTLP/gRPC** to the
   Collector on the same node. A Service with `internalTrafficPolicy: Local` keeps that traffic on the node.
2. Logs are written to **stdout as JSON**, with `trace_id` and `span_id` added by the logging instrumentation. The
   Collector's `filelog` receiver tails `/var/log/pods`. This is the pattern OpenTelemetry recommends for
   Kubernetes. It also collects logs from pods that are not instrumented, and it avoids depending on the
   OTel **Python logs SDK**, which is still at *Development* status.
3. The Collector runs `memory_limiter` (back-pressure), `k8sattributes` (pod, namespace and deployment metadata) and
   `batch`, then exports:
   - metrics to Prometheus `/api/v1/otlp/v1/metrics` (native OTLP receiver)
   - logs to Loki's native OTLP endpoint
   - traces to Tempo over OTLP
4. Tempo's **metrics-generator** derives RED span metrics and service-graph edges and **remote-writes** them to
   Prometheus. This gives a service map with no extra instrumentation.

### Flow 2: Health and infrastructure pull (Prometheus scrapes)

- The kubelet runs each container's `startup`, `liveness` and `readiness` probes (see [§6](#6-health-probe-design)).
  The results appear as pod readiness and restart counts.
- Prometheus **scrapes** kube-state-metrics (replica availability, readiness, restarts), kubelet and cAdvisor (CPU, memory and
  throttling), node-exporter, the **blackbox exporter**, and the self-metrics of the Collector, Loki and Tempo ("watch the watcher").
  Targets are declared with `ServiceMonitor`, `PodMonitor` and `Probe` resources, which the Prometheus Operator manages.
- The **blackbox exporter** calls each service's `/readyz` over HTTP from outside the pod. `probe_success == 0` is the
  signal for `ServiceDown`. It also catches a service that is running but unreachable, which in-process telemetry cannot report.
- **Why both push and pull?** Push (OTLP) gives one instrumentation path for all three signals. Pull
  gives Prometheus its built-in target health (`up`) and black-box checks for infrastructure. Pushed application metrics have
  no `up` series, so "is the service alive?" is answered by the blackbox probes and kube-state-metrics, not by whether telemetry is arriving.

### Flow 3: Detection and notification

![Alerting sequence](diagrams/alerting-sequence.svg)

<details>
<summary>Mermaid source (<a href="diagrams/alerting-sequence.mmd">alerting-sequence.mmd</a>)</summary>

```mermaid
sequenceDiagram
  autonumber
  participant Svc as Payment svc
  participant Col as OTel Collector
  participant Prom as Prometheus
  participant AM as Alertmanager
  participant Mail as Mailpit
  actor Eng as On-call engineer
  participant Graf as Grafana
  participant SAPI as Status API

  Svc->>Col: OTLP metrics (5xx rate rising)
  Col->>Prom: OTLP push (batched)
  loop every evaluation interval (30s)
    Prom->>Prom: evaluate PrometheusRules
  end
  Note over Prom: HighErrorRate for payment is pending, fires after the 5m for clause
  Prom->>AM: POST alert (severity=critical, service=payment)
  AM->>AM: group by alertname and service, dedupe, inhibit
  AM->>Mail: SMTP email with summary and runbook_url
  Mail-->>Eng: notification in inbox
  Eng->>Graf: open dashboard link from email
  Graf->>Prom: RED metrics and exemplars
  Note over Graf: exemplar links to Tempo trace, trace links to Loki logs
  SAPI->>AM: GET /api/v2/alerts
  SAPI->>Prom: GET /api/v1/query (error ratio, p95, ready replicas)
  Note over SAPI: payment shown as DEGRADED or DOWN on the status page
  Prom->>AM: alert resolved
  AM->>Mail: resolved email (send_resolved)
```

</details>

Prometheus evaluates `PrometheusRule` resources. An alert must stay true for its `for:` duration before it fires,
which suppresses flapping. Alertmanager groups, deduplicates and **inhibits** alerts, then routes them by
`severity`. Critical alerts email the on-call engineer. Each email includes a `runbook_url` and a dashboard link.
Details are in [§7](#7-detection-and-alerting-strategy).

### Flow 4: Visualization and query

- **Engineers use Grafana.** Its datasources are Prometheus (PromQL), Loki (LogQL), Tempo (TraceQL) and Alertmanager, with links
  between them: *exemplars → trace* (Prometheus to Tempo), *trace → logs* by `trace_id` (Tempo to Loki), and
  *log line → trace* through a derived field (Loki to Tempo), *trace → metrics*, and the service map from Tempo's service-graph
  metrics. Only two dashboards are provisioned as code, on purpose: Service Health Overview and Service Detail (templated by
  `$service`). Pipeline health is covered by alerts (Phase 5); anything else is ad hoc in Explore and the Drilldown apps.
- **Everyone else uses the status page.** It is a React and shadcn/ui single-page app served as static files from
  `status.localtest.me`. It polls the Status API on the same origin (`/api`, so no CORS) every 10 seconds. The Status API queries
  the Prometheus HTTP API (`/api/v1/query`) and the Alertmanager API (`/api/v2/alerts`) and caches results for 10 seconds, so page
  traffic never adds load to the monitoring backends. See [§8](#8-status-api-contract).

### Flow 5: Business request path

`k6 or browser → Envoy Gateway (api.localtest.me) → Order → {User, Payment}`. The W3C `traceparent` header is
propagated on every hop, so each order produces one distributed trace. Envoy Gateway also emits its own
OTLP traces and metrics through `EnvoyProxy` telemetry, which makes the edge the root span. NetworkPolicies permit
only the expected calls: the Gateway to the services, Order to User and Payment, every pod to the Collector and DNS, and Prometheus and the blackbox exporter to the probe and metrics ports.

## 5. Key decisions and trade-offs

| Decision | Chosen | Main alternative(s) | Why | Accepted trade-off |
|---|---|---|---|---|
| Instrumentation | OpenTelemetry SDK + OTLP | Prometheus client libraries, vendor agents | One vendor-neutral API for all three signals and the CNCF standard. Backends can be swapped. | The SDK is more complex than a Prometheus client. The Python logs SDK is not yet stable, so logs go through stdout. |
| Collector topology | One-tier **DaemonSet** locally. Agent + gateway in production. | Sidecar per pod, gateway only | Node-local, cheap, and adds Kubernetes metadata and log tailing. Lightest option for one node. | No central tail sampling and no persistent buffering locally |
| Tracing backend | **Tempo** | Jaeger v2 | Object-storage-only backend, TraceQL, Traces Drilldown, a metrics-generator for span metrics and the service graph, and native Grafana links | No standalone UI and no index-based search. Governed by Grafana Labs (AGPLv3) rather than CNCF-graduated like Jaeger. |
| Metrics | **Prometheus** (OTLP push + scrape) via kube-prometheus-stack | Mimir, VictoriaMetrics, OTel-only | The de facto standard. Native OTLP and remote-write receivers. The Operator and default rules are included. | A single node with local disk. Scaling needs Mimir or Thanos (see §11). |
| Logs | **Loki** | OpenSearch / Elasticsearch | Indexes labels only, so it is cheap and light, and it uses the same label model as Prometheus | Full-text search scans data. Label cardinality needs discipline. |
| Status view | Custom **Status API (BFF)** + status page in **React, Vite and shadcn/ui** | Grafana public dashboard, Uptime Kuma, Statuspage | A small, stable contract for non-experts. Hides PromQL and caches results. Accessible, consistent components that the Phase 6 shop page reuses. | An extra service plus a Node and pnpm build toolchain |
| Notification | **Alertmanager** → email (**Mailpit** locally) | Grafana Alerting, direct webhooks | Grouping, inhibition, silences and routing. Mature, and fits the Prometheus rules model. | Email is not real paging. Swap the receiver in production. |
| Edge | **Envoy Gateway** (Gateway API) | Traefik, ingress-nginx (retired) | Gateway API is the successor to Ingress. Built-in OIDC and JWT `SecurityPolicy`, so no oauth2-proxy. | More CRDs to learn. Heavier than Traefik (about 250–350 MB). |
| Identity | **Keycloak** (official Operator), realms `customers` and `ops` | Dex, a hosted identity provider | Open source, full OIDC support, and realms keep customer and staff identities apart | Heavy (JVM plus PostgreSQL, about 1–1.5 GB more RAM). Requires HTTPS. |
| Local runtime | **kind** on Docker (preferred) or Podman | k3d, minikube, Docker Compose | Conformant Kubernetes, also usable in CI, and the Makefile detects either container engine | The Podman provider is experimental and needs a rootful Podman machine |

## 6. Health probe design

Each service exposes two endpoints. The names follow the Kubernetes API server convention (`/livez`, `/readyz`).
Neither endpoint is routed through the Gateway, and both are excluded from tracing to keep traces clean.

| Probe | Endpoint | Question it answers | What it checks | Effect when it fails |
|---|---|---|---|---|
| **startupProbe** | `/livez` | "Has the process finished starting?" | Same as liveness, but with a longer `failureThreshold × periodSeconds` budget | Liveness and readiness are held back until it passes. The container is restarted if it never passes. |
| **livenessProbe** | `/livez` | "Is this process stuck and beyond recovery?" | Only the process itself: the event loop responds and no fatal internal state is set. **No dependency checks.** | The kubelet **restarts** the container |
| **readinessProbe** | `/readyz` | "Can *this instance* serve traffic right now?" | Instance-local readiness: startup has finished, the service is not draining after SIGTERM, and fault injection has not set it to not-ready | The pod is **removed from Service endpoints**. It is not restarted. |

**Why liveness never checks dependencies.** If `/livez` checked the database or a downstream service, an
outage in that shared dependency would fail liveness on **every** replica at the same time. The kubelet would
restart them all. That does not fix the dependency, it removes capacity, and it can cause a restart storm
that turns a partial outage into a total one. The Kubernetes documentation warns that a misconfigured liveness probe can
cause cascading failures. Liveness should detect only problems that a restart can fix, such as a deadlock.

**Why readiness does not check shared downstream services either.** If Order's `/readyz` checked
Payment, a Payment outage would remove *all* Order pods from the endpoints. Order would then fail completely,
including requests that do not need Payment. Instead, Order uses timeouts and returns errors for the calls that are
affected. The failure appears in metrics and alerts, and the status page shows it, without the scheduler taking
action. Readiness covers **instance-local** conditions only.

**Graceful shutdown.** On SIGTERM a service fails `/readyz` first, then drains in-flight requests
(a `preStop` delay plus `terminationGracePeriodSeconds`), then exits. This avoids returning 5xx during rollouts.

## 7. Detection and alerting strategy

**Principles** (from the [Prometheus alerting practices][prom-alerting] and [Google SRE][sre-monitoring] guidance):

- **Page on symptoms, not causes.** Critical alerts describe what users experience: the service is unreachable, requests fail or responses are slow.
  Causes such as pod restarts or pipeline problems are `warning` alerts and dashboard panels.
- **Every page must be actionable.** Each alert has `summary`, `description`, `runbook_url` and `dashboard_url` annotations.
  Every alert has a runbook in [`docs/runbooks/`](runbooks/README.md): symptoms, impact, triage queries, common causes and remediation.
- **Two severities.** `critical` pages the on-call engineer. `warning` goes to the team mailbox and never pages.
- **`for:` durations** stop transient spikes from firing alerts. Alertmanager `group_by: [alertname, service]`
  turns one incident into one notification.
- The thresholds below are **starting points**. They are tuned against SLOs once real traffic has been observed.

**Rule set** (Phase 5; plain Prometheus rule files in `deploy/charts/alerting/rules`, each alert unit-tested with `promtool test rules`
for a firing and a silent case). Recording rules compute per-`service` request rate, 5xx ratio and p95 from the OTLP histogram
`http_server_request_duration_seconds` (`/admin` excluded), so the alerts, the Status API and the dashboards use the same numbers:

| Alert | Condition | Severity |
|---|---|---|
| `ServiceDown` | blackbox `probe_success == 0` for 1m | critical |
| `HighErrorRate` | 5xx ratio > **5%** over 5m, for 5m, per service | critical |
| `HighLatencyP95` | p95 > **500 ms** over 5m, for 5m | warning (a second rule: critical for Payment above 1 s) |
| `ErrorBudgetBurn` | Order's 5xx ratio above 14.4 × 0.5 % over 1h **and** 5m (99.5% availability SLO), for 2m | critical |
| `PodNotReady` / `PodCrashLooping` | kube-state-metrics: not ready for 2m / `CrashLoopBackOff` for 5m, `service` from the pod label `app.kubernetes.io/name` | warning |
| `TelemetryPipelineDown` | Collector, Loki, Tempo or blackbox target down; no Collector at all; Collector exporter failures | warning |
| `Watchdog` | always firing; a dead man's switch | none |

Authentication failures (401 and 403, from Phase 6) are 4xx: they never count towards `HighErrorRate` or the SLO.

Error ratio (recording rule `service:http_server_errors:ratio_rate5m`):

```promql
sum by (service) (label_replace(rate(http_server_request_duration_seconds_count{k8s_namespace_name="apps", http_response_status_code=~"5..", http_route!~"/admin/.*"}[5m]), "service", "$1", "service_name", "(.+)"))
/
sum by (service) (label_replace(rate(http_server_request_duration_seconds_count{k8s_namespace_name="apps", http_route!~"/admin/.*"}[5m]), "service", "$1", "service_name", "(.+)"))
```

**Routing and inhibition (Alertmanager)**

- `severity="critical"` goes to the `oncall-email` receiver: `group_wait: 30s`, `group_interval: 5m`, `repeat_interval: 4h`, `send_resolved: true`.
- `severity="warning"` goes to the `team-email` receiver, with a longer repeat interval.
- `alertname="Watchdog"` goes to a `heartbeat` receiver every minute (a no-op locally). In production it goes to an external heartbeat service, which raises an alert if the alerting
  pipeline itself stops working.
- `group_by: [alertname, service]`; every notification is an HTML and text email with the summary, description, labels and links to the runbook,
  the dashboard, the Prometheus query and a pre-filled silence. Resolved notifications are sent too.
- **Inhibition:** `ServiceDown` inhibits `HighErrorRate`, `HighLatencyP95` and `ErrorBudgetBurn` when the `service` label matches. The on-call
  engineer gets one email about the cause, not several about its symptoms. The project's faster `PodNotReady`/`PodCrashLooping` also
  inhibit kube-prometheus-stack's generic `KubePodNotReady`/`KubePodCrashLooping` for the same pod.

**SLO burn-rate alert.** Given an availability SLO of 99.5% over 30 days for Order, which leaves a 0.5%
error budget, `ErrorBudgetBurn` is the fast-burn page of the **multi-window, multi-burn-rate** approach from the [SRE Workbook][sre-slo-alerting]:
burn rate above 14.4 over 1h **and** 5m. The slow-burn ticket (above 6 over 6h **and** 30m) and SLOs for the other services are the next
step; in production SLO alerts replace most fixed thresholds.

**Demo scenarios** (`scripts/demo.sh`, `make demo`): (a) Payment returns 30% errors → `HighErrorRate` email to on-call. (c) Payment scaled to 0
right after → `ServiceDown` email, and Payment's still active `HighErrorRate` is inhibited. (b) User adds 800 ms latency →
`HighLatencyP95` email to the team. (d) Order's readiness set to false → `PodNotReady`. The script checks the alert in Alertmanager,
the email in Mailpit (with its runbook and dashboard links) and the status page, then resets the fault and waits for the resolved emails.

## 8. Status API contract

The Status API is a backend for frontend written in FastAPI and instrumented with OTel. It converts raw telemetry into a **small, stable, read-only contract**
that the status page and any other consumer can use without knowing PromQL.

**Inputs for each service** (`user`, `order`, `payment`):

| Signal | Source |
|---|---|
| `probe_success` (blackbox `/readyz`) | Prometheus |
| `ready_replicas` / `desired_replicas` | Prometheus (kube-state-metrics) |
| `error_ratio_5m`, `latency_p95_ms`, `rps` (5-minute windows) and 30-minute sparkline series (1-minute windows) | Prometheus (OTLP `http_server_request_duration_seconds`, `/admin` excluded) |
| Active alerts (not silenced, not inhibited) for the service: label `service`, or `namespace` plus `deployment`/`container` for generic Kubernetes rules | Alertmanager `/api/v2/alerts` |

**Status rules** (all are evaluated; the worst result wins, in the order of the table. Thresholds are configuration and match the alert thresholds by default):

| Status | Rule |
|---|---|
| `DOWN` | The blackbox probe fails (`probe_success == 0`), **or** a `critical` alert is firing for the service |
| `DEGRADED` | A `warning` alert is firing for the service, **or** a threshold is breached (5xx ratio > 5% or p95 > 500 ms over 5 minutes, or fewer ready replicas than desired) |
| `UNKNOWN` | The data to decide is missing: Prometheus unreachable, or no probe result yet |
| `UP` | None of the above |

The status uses the **same signals and thresholds as alerting**, so the status page and the on-call email never contradict each other.
If Prometheus cannot be reached, the service is `UNKNOWN` (never a 500 and never a silent `UP`): `reasons[]` says so, `sources.prometheus`
is `unavailable`, and the last known metrics are kept with their `updated_at`. A `critical` alert still turns the service `DOWN`. If
Alertmanager cannot be reached, the metric rules still apply and the reason says that alerts were not considered. Alerts with severity
`none` or `info` (Watchdog, InfoInhibitor) are plumbing and are not returned.

**Endpoints (v1)**

| Method and path | Description |
|---|---|
| `GET /api/v1/services` | Overall `status`, and per service `status`, `reasons[]`, a metrics snapshot, sparkline `series`, its `alerts`, a Grafana link and `updated_at`; plus `sources`, `thresholds` and `generated_at` |
| `GET /api/v1/services/{name}` | A single service (404 for an unknown name) |
| `GET /api/v1/alerts` | Active alerts with a reduced set of fields (`name`, `service`, `severity`, `summary`, `description`, `runbook_url`, `starts_at`) |
| `GET /livez`, `GET /readyz` | Probes. `/readyz` does **not** fail when Prometheus is down, because the API can still answer and report the problem |

Results are cached on the server for 10 seconds (concurrent requests share one refresh) to protect Prometheus; each backend call
has a 3-second timeout. The full field list is in [services/README.md](../services/README.md#status-api).

Example response:

```json
{
  "name": "payment",
  "status": "DEGRADED",
  "reasons": ["5xx error ratio 7.8% > 5.0% (5m)"],
  "metrics": { "probe_success": true, "ready_replicas": 1, "desired_replicas": 1, "rps": 2.0, "error_ratio_5m": 0.0781, "latency_p95_ms": 4.9 },
  "series": { "rps": [{ "t": 1793485800, "v": 2.0 }], "error_ratio": [ ... ], "latency_p95_ms": [ ... ] },
  "alerts": [],
  "links": { "dashboard": "https://grafana.localtest.me/d/shd-service-detail/service-detail?var-service=payment" },
  "updated_at": "2026-10-31T22:31:15Z"
}
```

**Status page (Phase 4).** A React, TypeScript, Vite, Tailwind and [shadcn/ui][shadcn-vite] single-page app in `web/apps/status`.
It polls `/api/v1/services` every 10 seconds with TanStack Query and is built from shadcn components: `Card`, `Badge`, `Table`,
`Alert`, `Tooltip`, and shadcn Charts (Recharts) for rate, error and p95 sparklines. It supports dark mode and links into Grafana
(Explore and Traces Drilldown). The app lives in a pnpm monorepo created with shadcn's `--monorepo` option (`apps/status`,
`apps/shop`, `packages/ui` = `@workspace/ui`). It is built to static files and served by an `nginx-unprivileged` container behind
Envoy Gateway. The `status.localtest.me` route sends `/api` to the Status API and everything else to the static app, so both are on the same origin and no CORS is needed.

## 9. Networking

Every host is HTTPS only (Phase 6); plain HTTP redirects the browser hosts and serves nothing else.

| Hostname | Routes to | Access |
|---|---|---|
| `api.localtest.me` | User and Order services (path-based) | Bearer token of the `customers` realm (audience `shop-api`), checked by the gateway and again by the service |
| `shop.localtest.me` | Customer shop page (`/`), its API (`/api/orders` → Order, `/api/me` → User) | Customer login (`customers` realm), session held by the gateway |
| `status.localtest.me` | Status page (`/`) and Status API (`/api`) | Engineer login (`ops` realm), any group |
| `grafana.localtest.me` | Grafana | Grafana's own Keycloak login (`ops` realm): `sre` → Admin, `dev` → Editor, `viewer` → Viewer; local break-glass admin |
| `prometheus.localtest.me`, `alertmanager.localtest.me`, `mail.localtest.me` | Prometheus, Alertmanager, Mailpit (on-call inbox) | Engineer login (`ops` realm), group `sre` only |
| `sso.localtest.me` | Keycloak (login pages, OIDC endpoints, admin console) | Public |

- **Envoy Gateway** implements the Kubernetes **Gateway API**. There is one `Gateway` with a listener for `*.localtest.me`
  and `HTTPRoute`s per hostname; on `api.localtest.me` each service owns a route for its public path prefix (`/orders`, `/users`),
  so Payment, `/admin`, `/livez` and `/readyz` are not reachable through the edge. A `BackendTrafficPolicy` disables Envoy's
  panic mode so that the gateway, like a Kubernetes Service, never sends traffic to pods that are not ready. The Gateway API is the successor to Ingress, and the Kubernetes project has
  [retired ingress-nginx][ingress-nginx-retirement].
- **`localtest.me`** is a public wildcard DNS name. Every subdomain resolves to `127.0.0.1`, so normally no `/etc/hosts` changes are needed.
  `/etc/hosts` is the fallback if a resolver blocks it. kind `extraPortMappings` forward host ports 80 and 443 to the gateway NodePorts
  30080 and 30443, with `listenAddress: 127.0.0.1` so that nothing is exposed to the LAN. With Podman, a rootful Podman machine forwards these ports to macOS localhost.
  Exception: Podman on macOS publishes ports through the unprivileged `gvproxy`, and macOS only allows unprivileged binds below 1024 on the wildcard
  address, so there the ports bind to `0.0.0.0` (or use host ports ≥ 1024 on loopback); see [deploy/README.md](../deploy/README.md#troubleshooting).
- **CoreDNS rewrite.** Inside the cluster `*.localtest.me` would also resolve to `127.0.0.1`, which is the pod itself. A
  CoreDNS `rewrite` rule maps `*.localtest.me` to the gateway Service, so **the same URL works from the
  browser and from inside the cluster**. Phase 6 needs this: the OIDC issuer URL (`https://sso.localtest.me/realms/...`) must
  be identical for browsers and for in-cluster token validation.
- **TLS.** HTTPS terminates at the Gateway with a `*.localtest.me` wildcard certificate that **cert-manager** issues (and renews)
  from a CA `ClusterIssuer` backed by the **mkcert** local CA. Envoy Gateway's OIDC filter requires HTTPS redirect URLs, and session
  cookies are `Secure`. In-cluster clients (services, Grafana, k6, Envoy's own calls to Keycloak) trust the same CA, so every
  component uses the public URLs. Plain HTTP only redirects browser hosts; the API is not served over HTTP at all (a token sent
  in clear text is already leaked, so it is not redirected either). Inside the cluster, traffic behind the gateway is plain HTTP;
  production would add mTLS (service mesh) or re-encryption.
- **NetworkPolicy.** Every namespace (`apps`, `observability`, `identity`) denies all traffic by default. These flows are allowed: the Gateway to the apps, the apps to the Collector,
  Prometheus and the blackbox exporter to metrics and probe ports, and Order to User and Payment, plus DNS egress. In `observability`
  (Phase 5) every flow of the stack is listed explicitly: the Collector to the three stores, Grafana to its datasources,
  Alertmanager to Mailpit, the Status API to Prometheus and Alertmanager, the Gateway to the UIs, and the operators and sidecars to the API server. kindnet, the default
  CNI, has [enforced NetworkPolicy since kind v0.24][kind-v024].

## 10. Security and identity

![Identity and SSO sequence](diagrams/identity-sso-sequence.svg)

<details>
<summary>Mermaid source (<a href="diagrams/identity-sso-sequence.mmd">identity-sso-sequence.mmd</a>)</summary>

```mermaid
sequenceDiagram
  autonumber
  actor Ops as Engineer
  actor Cust as Customer
  participant GW as Envoy Gateway
  participant KC as Keycloak (sso.localtest.me)
  participant Prom as Prometheus UI
  participant Order as Order svc
  participant Pay as Payment svc

  rect rgb(235, 245, 255)
    Note over Ops,Prom: ops realm, OIDC + JWT SecurityPolicy, session cookie on .localtest.me
    Ops->>GW: GET https://prometheus.localtest.me
    GW-->>Ops: 302 to Keycloak (no session)
    Ops->>KC: log in once (also used by Grafana's own OAuth)
    KC-->>Ops: 302 to /oauth2/callback with code
    Ops->>GW: callback
    GW->>KC: code + PKCE verifier -> tokens (via the gateway, mkcert CA)
    GW-->>Ops: encrypted session cookies, 302 to the page
    Ops->>GW: GET with session cookie
    GW->>GW: JWT filter on the access token, allow group sre
    GW->>Prom: forward (viewer gets 403)
  end

  rect rgb(240, 255, 240)
    Note over Cust,Pay: customers realm, the shop as backend for frontend
    Cust->>GW: https://shop.localtest.me (same OIDC flow, own session)
    Cust->>GW: fetch POST /api/orders (cookie only, no token in JS)
    GW->>Order: POST /orders + Bearer customer token (aud shop-api)
    Order->>Order: validate JWT (JWKS), orders:write, user = token sub
    Order->>KC: client credentials (cached token, aud user-service + payment-service)
    Order->>Pay: POST /payments + Bearer order token, X-End-User-Sub
    Pay-->>Order: 201
    Order-->>Cust: 201 Created
    Note over GW,Order: api.localtest.me without a valid token: 401 at the gateway, never a 5xx
  end
```

</details>

**Goals:** customers sign in to a shop and place orders; engineers sign in once and reach every monitoring UI with permissions
by role; the business APIs and the calls between services are authenticated; and identity itself is observable.

**Identity provider: Keycloak**, deployed with the official **Keycloak Operator** (`Keycloak` and `KeycloakRealmImport` resources)
and a plain **PostgreSQL StatefulSet** (official image, 2 Gi PVC). Keycloak is open source, implements OIDC and OAuth 2.0 fully, and its
realms keep customer and staff identities apart. Dex was rejected because it federates to other providers instead of storing users
(no self-registration), and a hosted provider because it needs an external account and does not fit a self-contained demo. The
Bitnami chart is not used: its maintained images moved to a paid catalog in 2025. Realms, clients, roles, groups and mappers are
code (`KeycloakRealmImport`); secrets and demo passwords are generated per cluster and enter through placeholders. A realm import
only creates a realm, it never updates one, so changing a realm means deleting and importing it again (acceptable on a disposable
cluster; production would manage realms with a declarative tool such as keycloak-config-cli or Terraform).

| Realm | Users | Clients |
|---|---|---|
| `customers` | Customers (self-registration; roles `orders:read` and `orders:write` by default), demo user `customer` | `shop-gateway` (Envoy's OIDC login for the shop), `order-service` and `loadgen` (client credentials), `shop-api`, `user-service`, `payment-service` (audiences only) |
| `ops` | Groups `sre`, `dev`, `viewer`, one demo user each | `ops-gateway` (Envoy's OIDC login for the monitoring UIs, `groups` claim), `grafana` (Grafana's own OAuth) |

**Where authentication happens.**

- **At the edge, Envoy Gateway `SecurityPolicy`.** For browser UIs, Envoy's OAuth2 filter runs the authorization code flow with
  PKCE against Keycloak and keeps the result in **encrypted, HMAC-signed, HTTP-only cookies**. The engineers' login is one
  listener-level policy (cookies on `.localtest.me`): the status page's data, Prometheus, Alertmanager and Mailpit merge into it,
  so one login and one logout cover all four; route-level additions validate the forwarded access token again with the JWT
  filter, whose claims drive the authorization rule "group `sre` only" on the three monitoring UIs (other engineers get 403).
  Every route on the listener is protected unless it opts out (landing page, status page shell, Grafana and Keycloak, which log
  in themselves). `api.localtest.me` only validates bearer tokens (signature with cached JWKS, `iss`, `aud`, `exp`) and answers 401
  without calling a service. Envoy reaches Keycloak at its public URL through the gateway, with a `BackendTLSPolicy` that trusts the
  mkcert CA, so issuer, certificates and redirects are identical for browsers and the cluster.
- **Grafana** uses its **native Keycloak OAuth** instead of the gateway, because Grafana maps the `groups` claim to its own roles
  (`role_attribute_path`: `sre` → Admin, `dev` → Editor, `viewer` → Viewer; strict, so users in no group are refused). A local
  break-glass admin stays for when Keycloak is down.
- **In the services, again (defense in depth).** A shared FastAPI dependency in `shd_telemetry` validates the token itself and
  authorizes per endpoint: `orders:write` to place an order, `orders:read` to read; a customer only ever sees and creates their own
  orders (the order belongs to the token's subject). Probes, metrics and `/admin` need no token: they are not routed through the
  gateway, and NetworkPolicies limit who can reach them.
- **Between services: client credentials.** Order calls User and Payment with **its own** token (OAuth 2.0 client credentials,
  cached until shortly before it expires), not with the customer's. Its service account holds exactly the client roles `users:read`
  and `payments:write`, which also make `user-service` and `payment-service` the token's audiences; Payment accepts nothing else,
  so a customer token cannot charge a payment directly. The customer's subject travels in `X-End-User-Sub` and appears in the
  audit logs of User and Payment. Token exchange (RFC 8693) would carry the user's identity cryptographically and per-target tokens
  would narrow the audience further; both are the production refinements.
- **Customer shop: backend for frontend.** The shop (React and shadcn/ui, sharing `@workspace/ui`) never holds a token. Envoy runs
  the login and keeps the session; the page calls same-origin `/api/...` routes and the gateway adds the customer's access token
  (`forwardAccessToken`). This is the pattern that [OAuth 2.0 for Browser-Based Apps][oauth-bba] recommends as the most secure:
  an XSS bug cannot steal a token. Expired sessions answer `fetch()` calls with 401 instead of a redirect, and the page offers to
  sign in again. A single-page app holding tokens itself (authorization code with PKCE in JavaScript) was the rejected alternative.
- **Login and logout experience (Phase 6b).** A public landing page (https://home.localtest.me) is the entry point: "Customer
  login" is a plain link to the shop, which sends the browser to the `customers` realm's **branded login page** (a Keycloakify
  theme with the shop's shadcn/ui look, shipped in a custom Keycloak image); the engineering tools go through Keycloak's default
  theme (`ops` realm), so the redirect is visible. Every logout is **RP-initiated**: the gateway deletes its cookies and sends the
  browser to Keycloak's end-session endpoint with `id_token_hint` and `post_logout_redirect_uri=https://home.localtest.me/`, so the
  Keycloak session ends too and the next protected page asks for the password again. Envoy Gateway v1.9 does not expose that
  parameter yet; an `EnvoyPatchPolicy` sets it on Envoy's OAuth2 filter until the upstream field (on Envoy Gateway's main branch)
  is released ([sequence](diagrams/login-logout-sequence.svg), [details](../deploy/README.md#landing-page-login-and-logout-phase-6b)).
- **Load generator.** k6 uses a dedicated test client with the client credentials grant (`loadgen`); the password grant stays
  disabled for every client.

**401 and 403 are not errors of the service.** They are 4xx: they never count towards `HighErrorRate`, the SLO or the status page.
They are visible separately: the gateway's JWT and RBAC filter counters and the services' `auth_failures_total{reason}` on the
Overview dashboard's "Rejected requests (401/403)" panel.

**Observability of identity.** Keycloak exposes metrics on its management port (scraped through the operator's `ServiceMonitor`),
including user event metrics per realm (logins, failed logins with the error, client-credentials logins) and an HTTP latency
histogram, and sends OpenTelemetry traces to the Collector (gateway → Keycloak → PostgreSQL appears in the service graph). Alerts:
`KeycloakDown` (critical: nobody can sign in), `LoginFailureSpike` (more than 30 % failed logins with enough attempts) and
`TokenLatencyHigh` (p95 of the token endpoint above 500 ms); `KeycloakDown` inhibits the other two. The Overview dashboard has a
"Sign-ins (Keycloak)" panel.

**Hardening in the cluster.** Keycloak trusts the `X-Forwarded-*` headers of the gateway (edge TLS termination), so the operator's
NetworkPolicy lets only the Envoy proxies reach its HTTP port; otherwise any pod could spoof those headers. The management port is
open to Prometheus only, PostgreSQL to the identity namespace only. Every pod runs with the `restricted` Pod Security Standard.
The CA private key of mkcert is in the cluster (cert-manager signs with it): acceptable for a local cluster, never for a shared one.

## 11. Evolving to production

| Area | Local (this repo) | Production evolution |
|---|---|---|
| Collector | One-tier DaemonSet | **Agent (DaemonSet) + gateway (Deployment, HPA)** tiers. The gateway handles **tail sampling** (keep errors and slow traces), redaction, routing and persistent `sending_queue` storage. Use a `loadbalancing` exporter with trace-ID affinity. |
| Metrics | Single Prometheus with local TSDB | HA pairs plus **Thanos** or **Mimir** for global query, deduplication and long-term storage in object storage. Use recording rules for expensive queries. |
| Logs and traces | Loki and Tempo in single-binary mode on local disk | Microservices or simple-scalable mode with **object storage** (S3, GCS), retention by tenant, and caching |
| Alerting | One Alertmanager, email to Mailpit | An Alertmanager cluster (gossip), PagerDuty or Opsgenie for critical alerts, chat for warnings, an external dead man's switch, and SLO burn-rate alerts |
| Multi-cluster | One kind cluster | Agents in each cluster add `cluster` and `env` labels. A central or regional backend with multi-tenancy (`X-Scope-OrgID`). |
| Security | SSO at the gateway, JWT in the services, client credentials between services, default-deny NetworkPolicies, mkcert CA | A public CA (ACME) at the edge, mTLS inside (service mesh), token exchange for delegation, managed or HA Keycloak with a managed database, authentication on OTLP endpoints (Collector `auth` extensions), secrets in a vault, PII redaction in the Collector |
| Cost and cardinality | Low retention | Attribute allow-lists (`transform` and `filter` processors), limits per tenant, monitoring of active series, sampling, and log level and volume budgets |
| Delivery | Makefile + helmfile | CI (lint, test, Trivy, multi-arch images to GHCR, a kind end-to-end smoke test) and **Argo CD** pull-based GitOps |

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Laptop resources: the stack needs about 3.5–4.5 GB of RAM, and Keycloak adds about 1–1.5 GB | Slow or unstable cluster | Single-binary modes, 24-hour retention, requests and limits on every component, Keycloak only from Phase 6. Give the container VM at least 4 CPUs and 8 GB. |
| OTLP to Prometheus name translation (suffixes, dots, label promotion) | Dashboards and alerts break | Fix the translation strategy and the promoted resource attributes in Phase 3, and test queries in Phases 4 and 5 |
| Version-sensitive configuration (Prometheus Operator OTLP fields, Tempo chart values, Python exemplar support) | Configuration drift | Check against current documentation when each phase is implemented, and pin chart versions in helmfile |
| High-cardinality attributes (user IDs, order IDs) used as labels | Memory pressure and slow queries | Put IDs in spans and logs, never in metric labels. Promote only a few resource attributes. Keep Loki labels disciplined. |
| No buffering in the one-tier Collector | Data loss while a backend restarts | `memory_limiter` and `sending_queue` with retry. Persistent queue and gateway tier in production. |
| Pushed application metrics have no `up` series | A silent service looks healthy | Blackbox probes on `/readyz`, kube-state-metrics readiness, and `TelemetryPipelineDown` |
| The kind Podman provider is experimental, and a corporate VPN can disrupt VM networking | Setup friction | Docker is preferred. Podman runs in a dedicated rootful machine. The Makefile detects the engine and checks prerequisites. |
| Docker Hub rate limits | Image pulls fail | Prefer ghcr.io and quay.io images, or log in to docker.io |
| Monitoring stack fails together with the workload (same cluster) | Blind during incidents | Watchdog sent to an external heartbeat, and a separate monitoring cluster or SaaS in production |
| CoreDNS rewrite and HTTPS add complexity | Hard-to-debug failures | Done in separate phases (2 and 6), each with smoke tests |

## 13. References

Official documentation used for the claims in this document:

- OpenTelemetry: [Concepts](https://opentelemetry.io/docs/concepts/) ·
  [Python status](https://opentelemetry.io/docs/languages/python/) ·
  [Collector deployment patterns](https://opentelemetry.io/docs/collector/deploy/) ·
  [Collector components on Kubernetes (filelog, k8sattributes)](https://opentelemetry.io/docs/platforms/kubernetes/collector/components/) ·
  [HTTP metrics semantic conventions](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/) ·
  [Sampling](https://opentelemetry.io/docs/concepts/sampling/)
- Prometheus: [Using Prometheus as an OpenTelemetry backend](https://prometheus.io/docs/guides/opentelemetry/) ·
  [HTTP API (incl. remote-write receiver)](https://prometheus.io/docs/prometheus/latest/querying/api/) ·
  [Alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/) ·
  [Alerting practices][prom-alerting] ·
  [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/) ·
  [Alertmanager configuration](https://prometheus.io/docs/alerting/latest/configuration/) ·
  [Blackbox exporter](https://github.com/prometheus/blackbox_exporter) ·
  [kube-prometheus-stack chart](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- Grafana: [Loki overview](https://grafana.com/docs/loki/latest/get-started/overview/) ·
  [Loki OTLP ingestion](https://grafana.com/docs/loki/latest/send-data/otel/) ·
  [Loki label best practices](https://grafana.com/docs/loki/latest/get-started/labels/bp-labels/) ·
  [Tempo](https://grafana.com/docs/tempo/latest/) ·
  [Tempo metrics-generator](https://grafana.com/docs/tempo/latest/metrics-generator/) ·
  [Tempo data source and trace-to-logs](https://grafana.com/docs/grafana/latest/datasources/tempo/configure-tempo-data-source/)
- Kubernetes: [Probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/) ·
  [Configure probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/) ·
  [API health endpoints (`/livez`, `/readyz`)](https://kubernetes.io/docs/reference/using-api/health-checks/) ·
  [Network policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/) ·
  [Customizing DNS](https://kubernetes.io/docs/tasks/administer-cluster/dns-custom-nameservers/) ·
  [Ingress NGINX retirement][ingress-nginx-retirement]
- Edge and identity: [Gateway API](https://gateway-api.sigs.k8s.io/) ·
  [Envoy Gateway](https://gateway.envoyproxy.io/docs/) ·
  [Envoy Gateway OIDC](https://gateway.envoyproxy.io/docs/tasks/security/oidc/) ·
  [Envoy Gateway JWT](https://gateway.envoyproxy.io/docs/tasks/security/jwt-authentication/) ·
  [CoreDNS rewrite plugin](https://coredns.io/plugins/rewrite/) ·
  [Keycloak documentation](https://www.keycloak.org/documentation) ·
  [Keycloak Operator](https://www.keycloak.org/operator/installation) ·
  [Keycloak realm import](https://www.keycloak.org/operator/realm-import) ·
  [OAuth 2.0 for Browser-Based Apps][oauth-bba] ·
  [mkcert](https://github.com/FiloSottile/mkcert) · [cert-manager](https://cert-manager.io/docs/)
- Frontend: [shadcn/ui with Vite (including monorepo)][shadcn-vite]
- Runtime: [kind quick start (incl. Podman provider)](https://kind.sigs.k8s.io/docs/user/quick-start/) ·
  [kind configuration (extraPortMappings)](https://kind.sigs.k8s.io/docs/user/configuration/#extra-port-mappings) ·
  [kind v0.24.0 release (NetworkPolicy in kindnet)][kind-v024] ·
  [Helm](https://helm.sh/docs/) · [Helm and CRDs][helm-crds] · [helmfile](https://helmfile.readthedocs.io/) · [helm-diff](https://github.com/databus23/helm-diff) ·
  [Mailpit](https://mailpit.axllent.org/) · [k6](https://grafana.com/docs/k6/latest/)
- SRE practice: [Monitoring distributed systems (four golden signals)][sre-monitoring] ·
  [Alerting on SLOs (multi-window, multi-burn-rate)][sre-slo-alerting] ·
  [RED method](https://grafana.com/blog/2018/08/02/the-red-method-how-to-instrument-your-services/)

[prom-alerting]: https://prometheus.io/docs/practices/alerting/
[sre-monitoring]: https://sre.google/sre-book/monitoring-distributed-systems/
[sre-slo-alerting]: https://sre.google/workbook/alerting-on-slos/
[ingress-nginx-retirement]: https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/
[shadcn-vite]: https://ui.shadcn.com/docs/installation/vite
[oauth-bba]: https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/
[kind-v024]: https://github.com/kubernetes-sigs/kind/releases/tag/v0.24.0
[helm-crds]: https://helm.sh/docs/chart_best_practices/custom_resource_definitions/
