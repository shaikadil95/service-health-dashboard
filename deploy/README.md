# Local Kubernetes platform (Phase 2)

One command creates a single-node [kind](https://kind.sigs.k8s.io/) cluster on Docker or Podman, installs
[Envoy Gateway](https://gateway.envoyproxy.io/) as the edge and deploys the User, Order and Payment services with
probes, hardened pods and default-deny NetworkPolicies.

```bash
make up       # prereqs -> kind cluster -> build + load images -> helmfile apply -> CoreDNS rewrite -> status
make verify   # automated checks (gateway routes, in-cluster URL, NetworkPolicy, readiness semantics)
make down     # delete the cluster
```

```bash
curl -s -X POST http://api.localtest.me/orders -H 'content-type: application/json' \
  -d '{"user_id":"u-1001","items":[{"sku":"book","quantity":2,"unit_price":"12.50"}],"currency":"EUR"}'
curl -s http://api.localtest.me/orders/<id>
curl -s http://api.localtest.me/users/u-1001
```

If `api.localtest.me` does not resolve on your machine, see [Troubleshooting](#troubleshooting).

## Architecture

```mermaid
flowchart LR
  host(["curl / browser<br/>api.localtest.me:80"]) -->|kind port mapping<br/>80 -> 30080| svc
  subgraph egs["envoy-gateway-system"]
    eg["Envoy Gateway<br/>controller"] -. xDS .-> envoy
    svc["Service envoy-edge<br/>NodePort 30080"] --> envoy["Envoy proxy<br/>Gateway edge"]
  end
  subgraph apps["apps (default deny)"]
    order["order"] --> user["user"]
    order --> payment["payment<br/>(internal only)"]
  end
  envoy -->|"/orders"| order
  envoy -->|"/users"| user
  pod(["pod in any namespace"]) -->|"api.localtest.me<br/>CoreDNS rewrite"| svc
```

| Piece | Where | What it does |
|---|---|---|
| kind cluster `shd` | [`kind/kind-config.yaml`](kind/kind-config.yaml) | One node, `kindest/node:v1.36.4` pinned by digest, host ports 80/443 → NodePorts 30080/30443 |
| Envoy Gateway v1.9.3 | release `envoy-gateway`, [`values/envoy-gateway.yaml`](values/envoy-gateway.yaml) | Controller from `oci://docker.io/envoyproxy/gateway-helm`; the chart also installs the Gateway API v1.6.1 CRDs |
| Edge | release `edge`, [`charts/edge`](charts/edge) | `EnvoyProxy` (NodePort Service with the fixed name `envoy-edge`), `GatewayClass` and `Gateway` `edge` (HTTP listener on 80 for `*.localtest.me`), `BackendTrafficPolicy` |
| Namespace baseline | release `apps-baseline`, [`charts/namespace-baseline`](charts/namespace-baseline) | `default-deny-all` (ingress and egress) and `allow-dns-egress` |
| Services | releases `user`, `order`, `payment`, [`charts/microservice`](charts/microservice) + [`values/<svc>.yaml`](values) | Deployment, Service (port 80 → 8080), ServiceAccount, NetworkPolicy, HTTPRoute |
| Namespaces | [`scripts/namespaces.sh`](scripts/namespaces.sh) | Creates `apps` and `envoy-gateway-system` with Pod Security Admission `restricted` (enforce, warn, audit) |
| CoreDNS | [`scripts/coredns-localtest.sh`](scripts/coredns-localtest.sh) | `*.localtest.me` → `envoy-edge.envoy-gateway-system.svc.cluster.local` inside the cluster |

[`helmfile.yaml`](helmfile.yaml) orders the releases with `needs`: Envoy Gateway (with its CRDs) first, then the edge, the
namespace baseline and the services. Phase 3 adds its releases (Collector, kube-prometheus-stack, Loki, Tempo, …) to the
same file in an `observability` namespace.

### Versions

| Component | Version | Evidence |
|---|---|---|
| kind | ≥ 0.33.0 | Node image digest taken from the [v0.33.0 release notes](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0), which require digest pinning |
| Kubernetes (node) | v1.36.4 | kind 0.33 defaults to v1.37.0, but [Envoy Gateway v1.9 is tested on 1.33–1.36](https://gateway.envoyproxy.io/news/releases/matrix/) |
| kubectl | 1.35–1.37 | [Version skew policy](https://kubernetes.io/releases/version-skew-policy/#kubectl): ±1 minor of the API server |
| Envoy Gateway | v1.9.3 (latest stable; v1.10 is still a release candidate) | Gateway API v1.6.1, Envoy distroless v1.39.x |
| Helm / helmfile / helm-diff | 4.x / 1.8 / 3.15 | `make prereqs` checks them |
| CoreDNS | v1.14.2 (from the node image) | Supports `rewrite … answer auto` |

## Make targets

| Target | What it does |
|---|---|
| `make prereqs` | Engine reachable (Podman must be **rootful**), ≥ 4 CPUs / 8 GiB, kind ≥ 0.33, kubectl within skew of the node image, Helm 4, helm-diff, helmfile |
| `make cluster-up` / `cluster-down` | Create (idempotent) or delete the kind cluster |
| `make images` | `make build`, then load the images into kind. Docker: `kind load docker-image`. Podman: `podman save -m` to one archive → `kind load image-archive` |
| `make deploy` | Namespaces with PSA labels → `helmfile apply` → wait for `Gateway` `Programmed` → CoreDNS rewrite. Idempotent |
| `make up` / `make down` | `cluster-up images deploy status` / `cluster-down` |
| `make redeploy` | Rebuild and reload the images, then `rollout restart` the services (the tag stays `dev`) |
| `make status` | Nodes, Gateway and HTTPRoutes, Envoy Service, workloads and NetworkPolicies |
| `make verify` | Loads the `curl` test image into kind, then runs [`scripts/verify.sh`](scripts/verify.sh), see [Verification](#verification) |
| `make lint-charts` | `helm lint --strict` and `helm template` for the local charts with every values file |

The engine is detected as in Phase 1 (Podman if it is running, otherwise Docker; `make ENGINE=docker …` forces one).
With Podman the Makefile exports `KIND_EXPERIMENTAL_PROVIDER=podman`. Every `kubectl` and `helmfile` call uses the
`kind-shd` context explicitly, so another current context is never touched.

## Edge and routing

**Envoy proxy Service.** Envoy Gateway creates the proxy Deployment and Service per `Gateway`. The `EnvoyProxy`
resource (referenced by the `GatewayClass`) sets the Service type to `NodePort`, gives it the stable name `envoy-edge`
(`envoyService.name`) and pins `nodePort: 30080` for port 80 with a strategic-merge `patch`, because the API has no
`nodePort` field. The HTTPS listener (443 → 30443) is added in Phase 6; patching a port that does not exist yet would
create a broken Service port. The Envoy container listens on 10080 (Envoy Gateway shifts privileged ports because the
proxy runs as non-root).

**What is exposed on `api.localtest.me`:**

| Path | Backend | Why |
|---|---|---|
| `/orders`, `/orders/{id}` | order | Public business API |
| `/users/{id}` | user | Public business API |
| `/payments` | – (404 at the edge) | Payment is internal; only order may call it |
| `/admin/*`, `/livez`, `/readyz`, `/docs` | – (404 at the edge) | Operational endpoints stay inside the cluster |

Each service chart renders its own `HTTPRoute` with `PathPrefix` matches (Gateway API prefixes match whole path
segments, so `/ordersX` does not match). Anything else has no rule, so Envoy answers 404 without calling a service.
Envoy normalizes paths before routing (`/orders/../admin/faults` → `/admin/faults`), and escaped slashes get a 307 to
the unescaped path (Envoy Gateway's default `UnescapeAndRedirect`), so traversal tricks also end in 404. The `Gateway`
only accepts routes from the namespaces listed in `gateway.routeNamespaces` (`apps` now; Phase 3 adds `observability`).

**BackendTrafficPolicy: readiness at the edge.** Envoy Gateway marks endpoints whose pod is not ready as `DRAINING`.
With Envoy's default [panic threshold](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/panic_threshold)
of 50 %, a service whose pods are *all* not ready still received traffic through the gateway (verified: 200 instead of 503).
`healthCheck.panicThreshold: 0` disables panic mode, so the edge behaves like a Kubernetes Service: no ready pod, no
traffic, 503. No gateway retries or extra timeouts are configured on purpose: `POST /orders` is not idempotent, and
the services own their upstream timeouts (Envoy's default 15 s route timeout applies).

## Same URL inside and outside the cluster (CoreDNS)

Public DNS resolves `*.localtest.me` to `127.0.0.1`. Inside a pod that is the pod itself, so a CoreDNS
[`rewrite`](https://coredns.io/plugins/rewrite/) rule maps the names to the gateway Service instead:

```
rewrite stop {
    name regex ^(.+\.)?localtest\.me\.$ envoy-edge.envoy-gateway-system.svc.cluster.local. answer auto
}
```

`answer auto` rewrites the answer back to the queried name, so clients get an A record for `api.localtest.me`
(the `envoy-edge` ClusterIP). The regex is anchored, so search-path expansions such as
`api.localtest.me.apps.svc.cluster.local.` are not rewritten and fall through to NXDOMAIN as usual.
This matters from Phase 6, when browsers and pods must use the same OIDC issuer URL.

The script edits the `kube-system/coredns` ConfigMap as the [Kubernetes DNS customization guide](https://kubernetes.io/docs/tasks/administer-cluster/dns-custom-nameservers/)
describes. It is **idempotent**: the rule sits between `BEGIN`/`END` marker comments, is replaced on each run, and
CoreDNS is restarted only if the Corefile changed (the `reload` plugin would also pick it up, but only after one to
two minutes). kubeadm does not reconcile this ConfigMap after cluster creation, so the change lasts for the life of the cluster.

## Workloads (`charts/microservice`)

| Concern | Setting | Reason |
|---|---|---|
| startupProbe | `/livez`, every 2 s, 30 failures (60 s budget) | Protects slow starts; liveness only starts afterwards |
| livenessProbe | `/livez`, every 10 s, timeout 2 s, 3 failures | Event loop only, never dependencies → no cascading restarts |
| readinessProbe | `/readyz`, every 5 s, timeout 2 s, 2 failures | Out of the endpoints within ~10 s when starting, draining or forced not-ready |
| Graceful shutdown | `preStop: sleep 5` (native sleep action), `SHUTDOWN_DRAIN_SECONDS=3`, `SHUTDOWN_TIMEOUT_SECONDS=10`, `terminationGracePeriodSeconds: 25` | Endpoint removal propagates before SIGTERM; then the service fails `/readyz`, drains and finishes in-flight requests. The chart fails to render if the grace period is not larger than the sum |
| Resources | requests 50m / 128Mi, limits 500m / 256Mi | Laptop-sized; memory limit as in compose |
| Pod security | `runAsNonRoot` (UID/GID 10001), `readOnlyRootFilesystem`, drop `ALL` capabilities, `allowPrivilegeEscalation: false`, `seccompProfile: RuntimeDefault` | Meets the `restricted` Pod Security Standard, which the `apps` namespace enforces. No `/tmp` volume is needed: the image writes nothing at runtime |
| API access | Dedicated ServiceAccount per service, `automountServiceAccountToken: false`, `enableServiceLinks: false` | The services never call the Kubernetes API |
| Rollouts | `maxUnavailable: 0`, `maxSurge: 1` | No capacity drop during a rollout |
| OpenTelemetry | `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` (`deployment.environment.name=kind`, `k8s.namespace.name`, `k8s.pod.name`, `k8s.pod.uid`, `k8s.node.name`, `k8s.deployment.name`, `k8s.container.name`, `service.instance.id=<namespace>.<pod>.<container>` from the downward API), `OTEL_SEMCONV_STABILITY_OPT_IN=http`, `OTEL_LOGS_EXPORTER=none` | `service.instance.id` follows the [OTel Kubernetes guidance](https://opentelemetry.io/docs/specs/semconv/non-normative/k8s-attributes/) |
| OTLP export | `otel.exporter.enabled: false` → `OTEL_TRACES_EXPORTER=none`, `OTEL_METRICS_EXPORTER=none` | There is no Collector until Phase 3, so no export errors are logged. Phase 3 sets `enabled: true` and `endpoint` |

## NetworkPolicies (`apps`)

kindnet, kind's default CNI, [enforces NetworkPolicy since kind v0.24](https://github.com/kubernetes-sigs/kind/releases/tag/v0.24.0).
Policies are additive allow-lists on top of the namespace default deny.

| Policy | Selects | Allows |
|---|---|---|
| `default-deny-all` | all pods | nothing (ingress and egress) |
| `allow-dns-egress` | all pods | egress to `kube-system` `k8s-app=kube-dns` on 53/UDP and 53/TCP |
| `user` | user | ingress on 8080 from the Envoy pods of Gateway `edge` and from order |
| `order` | order | ingress on 8080 from the Envoy pods; egress to user and payment on 8080 |
| `payment` | payment | ingress on 8080 from order only |

- The Envoy pods are selected by namespace (`kubernetes.io/metadata.name: envoy-gateway-system`) **and** their labels
  (`app.kubernetes.io/name: envoy`, `app.kubernetes.io/component: proxy`, `gateway.envoyproxy.io/owning-gateway-name: edge`).
- Rules use the pod port (8080): NetworkPolicy sees traffic after the Service has translated port 80.
- Kubelet probes come from the node and are not blocked; `kubectl port-forward` enters the pod's network namespace
  directly, so `/admin/faults` stays reachable for operators but not from other pods.
- **Phase 3:** `networkPolicy.otelCollector.enabled: true` adds egress to the `observability` namespace on 4317/4318
  (and a pod selector if needed). If the Collector is reached through a host port, an `ipBlock` for the node IP is needed instead.

## Verification

`make verify` ([`scripts/verify.sh`](scripts/verify.sh)) checks the exit criteria against the running cluster. It uses
`curl --resolve api.localtest.me:80:127.0.0.1` on the host so it does not depend on the host resolver, and a throwaway
`curl` pod in a `netcheck` namespace (outside `apps`) for the in-cluster checks.

Evidence from `make down && make up && make verify` (Podman 6.1.4 rootful machine, macOS arm64), trimmed:

```text
$ make down && make up        # from scratch: 376 s (two runs: 376 s and 468 s; mostly Envoy Gateway image pulls)
Container engine: podman
  ok    podman 6.1.4, rootful, running
  ok    engine resources: 4 CPUs / 9 GiB
  ok    kind v0.33.0
  ok    kubectl v1.37.2 (node image v1.36)
  ok    helm v4.3.1
  ok    helm-diff plugin
  ok    helmfile version v1.8.2
WARNING: gateway ports 80/443 bind to 0.0.0.0 (reachable from the network); see deploy/README.md
...
NAME            NAMESPACE              CHART                                     VERSION   DURATION
apps-baseline   apps                   ./charts/namespace-baseline               0.1.0           0s
envoy-gateway   envoy-gateway-system   oci://docker.io/envoyproxy/gateway-helm   v1.9.3       1m48s
edge            envoy-gateway-system   ./charts/edge                             0.1.0           0s
payment         apps                   ./charts/microservice                     0.1.0           3s
user            apps                   ./charts/microservice                     0.1.0           3s
order           apps                   ./charts/microservice                     0.1.0           3s
coredns: *.localtest.me -> envoy-edge.envoy-gateway-system.svc.cluster.local (configured, CoreDNS restarted)

$ make verify
== 1. Readiness of the platform
  PASS  Gateway envoy-gateway-system/edge Programmed=True
  PASS  deployment apps/user available
  PASS  deployment apps/order available
  PASS  deployment apps/payment available
== 2. Host -> gateway (http://api.localtest.me:80)
  WARN  host DNS does not resolve api.localtest.me; add it to /etc/hosts (see deploy/README.md)
  PASS  POST /orders -> 201
  PASS  GET /orders/32c2dacf27d2 -> 200
  PASS  GET /users/u-1001 -> 200
  PASS  GET /payments (not exposed) -> 404
  PASS  GET /admin/faults (not exposed) -> 404
  PASS  GET /livez (not exposed) -> 404
  PASS  GET /readyz (not exposed) -> 404
  PASS  GET /docs (not exposed) -> 404
  PASS  GET /orders/../admin/faults (not exposed) -> 404
  PASS  GET /orders/%2e%2e/admin/faults (not exposed) -> 404
  PASS  GET /users/..%2fadmin/faults (not exposed) -> 404
  PASS  POST /payments (not exposed) -> 404
  PASS  PUT /admin/faults (not exposed) -> 404
== 3. Pod -> gateway via CoreDNS rewrite (namespace netcheck, outside apps)
  PASS  api.localtest.me resolves in-cluster to the envoy-edge Service -> 10.96.232.202
  PASS  pod: POST http://api.localtest.me/orders -> 201
  PASS  pod: GET http://api.localtest.me/users/u-1001 -> 200
== 4. NetworkPolicy (default deny in apps)
  PASS  pod outside apps -> payment.apps directly (blocked) -> 000
  PASS  pod outside apps -> user.apps directly (blocked) -> 000
  PASS  pod outside apps -> order.apps directly (blocked) -> 000
  PASS  order -> user and order -> payment allowed (POST /orders returned 201 above)
== 5. Readiness probe: not ready => out of endpoints, not restarted
  PASS  EndpointSlice user: endpoint ready (after 8 s) -> false
  PASS  gateway GET /users/u-1001 while not ready -> 503
  PASS  /livez still healthy -> 200
  PASS  restartCount unchanged after 35 s -> 0
  PASS  EndpointSlice user: endpoint ready after restore -> true
  PASS  gateway GET /users/u-1001 after restore -> 200

verify: 30 passed, 0 failed

$ make cluster-up deploy      # second run: idempotent, 5 s
kind cluster 'shd' already exists
coredns: *.localtest.me rewrite already present (unchanged)

# Graceful shutdown: 150 requests (every 0.2 s) through the gateway during `kubectl rollout restart deploy/user`
    150 200
```

Before the `BackendTrafficPolicy` was added, check 5 returned **200** instead of 503 through the gateway (Envoy panic
mode, see [Edge and routing](#edge-and-routing)), although the EndpointSlice already showed `ready=false`.

Readiness by hand:

```bash
kubectl -n apps port-forward deploy/user 18081:8080 &
curl -X PUT localhost:18081/admin/faults -H 'content-type: application/json' -d '{"ready":false}'
kubectl -n apps get endpointslice -l kubernetes.io/service-name=user \
  -o jsonpath='{.items[*].endpoints[*].conditions}'   # ready=false, pod not restarted
curl -X DELETE localhost:18081/admin/faults
```

## Troubleshooting

**`api.localtest.me` does not resolve on the host.** Some resolvers (home routers, corporate DNS) drop public answers that
point to private addresses (DNS-rebinding protection). Check with `dig +short api.localtest.me @1.1.1.1` (should print
`127.0.0.1`) and `dscacheutil -q host -a name api.localtest.me` (empty if your resolver filters it). Fix it with
`/etc/hosts` (needs admin rights) or test with `curl --resolve api.localtest.me:80:127.0.0.1 …`:

```text
127.0.0.1 api.localtest.me grafana.localtest.me prometheus.localtest.me alertmanager.localtest.me status.localtest.me mail.localtest.me
```

**Podman on macOS: port 80 binds to `0.0.0.0`.** The Podman machine publishes ports through `gvproxy`, which runs as
your user. macOS lets unprivileged processes bind ports below 1024 only on the wildcard address, so
`listenAddress: 127.0.0.1` fails with `bind: permission denied`. On Podman + macOS the Makefile therefore writes a copy of
the kind config with `listenAddress: "0.0.0.0"` (and prints a warning). The gateway is then reachable from your network
unless the macOS firewall blocks incoming connections (System Settings → Network → Firewall; check with
`/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate`). Only the routed business APIs are exposed in Phase 2.
To keep everything on loopback instead, use Docker (Docker Desktop binds privileged ports through a privileged helper), or
use unprivileged host ports: `make down && make up GATEWAY_LISTEN_ADDRESS=127.0.0.1 GATEWAY_HTTP_PORT=8080 GATEWAY_HTTPS_PORT=8443`.
URLs from the host then need the port (`http://api.localtest.me:8080`), while pods keep using port 80.

**Podman must be rootful.** kind's Podman provider is experimental and needs a rootful machine:
`podman machine stop && podman machine set --rootful && podman machine start`. `make prereqs` checks it.

**`docker-credential-desktop: executable file not found`.** Helm falls back to `~/.docker/config.json` for OCI registry
credentials. If that file still names `"credsStore": "desktop"` after Docker Desktop was removed, every chart pull
fails, including anonymous ones. The Makefile detects a missing credential helper and runs helmfile with
`DOCKER_CONFIG=.cache/docker-config` (an empty config), so public charts are pulled anonymously; your file is not changed.

**kubectl version skew.** `make prereqs` fails if the first `kubectl` in `PATH` is not within one minor version of the node
(1.35–1.37). Put the newer kubectl first in `PATH` or run `make KUBECTL=/path/to/kubectl …`.

**Slow or failing image pulls inside the node (Podman).** The kind node resolves registries through the Podman network's
DNS (`10.89.0.1`), which sometimes answers `server misbehaving`. The kubelet retries, so Envoy Gateway still comes up,
but the first `make up` can take several minutes. Images that the platform builds or tests with (`make images`,
`make verify`) are therefore pulled by the engine on the host side and loaded into kind instead of being pulled by the node.

**Docker Hub rate limits.** The Envoy Gateway chart and images, `kindest/node` and the `curl` test image come from Docker
Hub. Log in with `podman login docker.io` / `docker login` if pulls are throttled.

**Code changes do not show up.** The images keep the tag `dev`, so a new `make images` does not restart pods. Use
`make redeploy`.

**Upgrading Envoy Gateway.** Helm installs CRDs from a chart's `crds/` directory once and never upgrades them. Apply the
new Gateway API and Envoy Gateway CRDs before bumping the chart version
([upgrade guide](https://gateway.envoyproxy.io/docs/install/install-helm/#upgrading-from-the-previous-version)).
