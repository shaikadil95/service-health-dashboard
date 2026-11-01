# Service Health Dashboard. Run `make help` for targets.
# Phase 1: services (uv, compose). Phase 2: local Kubernetes platform (kind, Helm, helmfile).
# Phase 3: telemetry pipeline and storage (Collector, Prometheus, Loki, Tempo, Grafana, k6).
# Phase 4: Grafana correlations and dashboards, Status API and status page (web/, pnpm).
# Phase 5: alert rules (promtool-tested), Alertmanager routing to Mailpit, runbooks, scripts/demo.sh.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

# Container engine: Podman if it is installed and running, otherwise Docker.
# Override with `make ENGINE=docker ...`.
ENGINE ?= $(shell podman info >/dev/null 2>&1 && echo podman || echo docker)
COMPOSE ?= $(ENGINE) compose
SERVICES := user-service order-service payment-service status-api
# Static web apps in the pnpm monorepo web/ (image <app>-web, served by nginx-unprivileged).
WEB_APPS := status shop
IMAGE_PREFIX ?= localhost/shd
IMAGE_TAG ?= dev
COLLECTOR_IMAGE := $(shell awk '/opentelemetry-collector-contrib:/ {print $$2}' compose.yaml)
SERVICE_IMAGES := $(foreach svc,$(SERVICES),$(IMAGE_PREFIX)/$(svc):$(IMAGE_TAG))
WEB_IMAGES := $(foreach app,$(WEB_APPS),$(IMAGE_PREFIX)/$(app)-web:$(IMAGE_TAG))

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^##@/ {printf "\n%s\n", substr($$0, 5)} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Services (Phase 1)

.PHONY: sync
sync: ## Install the uv workspace (all services + dev tools) into .venv
	uv sync --all-packages --locked

.PHONY: lint
lint: sync rules-lint ## Lint: ruff, formatting, uv.lock up to date, alert rules and Alertmanager config
	uv lock --check
	uv run ruff check .
	uv run ruff format --check .

.PHONY: fmt
fmt: sync ## Auto-fix lint findings and format the code
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: test
test: sync rules-test ## Run the unit tests (pytest) and the alert rule and Alertmanager routing tests
	uv run pytest

# Alert rules and Alertmanager configuration (deploy/charts/alerting) are checked with promtool and
# amtool from the same Prometheus and Alertmanager versions as kube-prometheus-stack, run through the
# container engine, so no local install is needed.
PROMETHEUS_IMAGE := quay.io/prometheus/prometheus:v3.15.1
ALERTMANAGER_IMAGE := quay.io/prometheus/alertmanager:v0.34.2
ALERTING_CHART := $(CURDIR)/deploy/charts/alerting
PROMTOOL_RUN := $(ENGINE) run --rm --entrypoint sh -v "$(ALERTING_CHART):/work:ro" -w /work $(PROMETHEUS_IMAGE) -c
AMTOOL_RUN := $(ENGINE) run --rm --entrypoint sh -v "$(ALERTING_CHART)/alertmanager:/etc/alertmanager/config:ro" \
  -v "$(ALERTING_CHART)/tests:/tests:ro" $(ALERTMANAGER_IMAGE) -c

.PHONY: rules-lint
rules-lint: ## promtool check rules and amtool check-config (alerting chart)
	$(PROMTOOL_RUN) 'promtool check rules rules/*.rules.yaml'
	$(AMTOOL_RUN) 'amtool check-config /etc/alertmanager/config/alertmanager.yaml'

.PHONY: rules-test
rules-test: ## promtool unit tests of every alert rule; Alertmanager routing and email template tests
	$(PROMTOOL_RUN) 'promtool test rules tests/*.test.yaml'
	$(AMTOOL_RUN) /tests/alertmanager.test.sh

.PHONY: build
build: ## Build the service and web images with the container engine
	@for svc in $(SERVICES); do \
	  echo "==> $(IMAGE_PREFIX)/$$svc:$(IMAGE_TAG)"; \
	  $(ENGINE) build -f services/Dockerfile --build-arg SERVICE=$$svc \
	    -t $(IMAGE_PREFIX)/$$svc:$(IMAGE_TAG) . ; \
	done
	@for app in $(WEB_APPS); do \
	  echo "==> $(IMAGE_PREFIX)/$$app-web:$(IMAGE_TAG)"; \
	  $(ENGINE) build -f web/Dockerfile --build-arg APP=$$app \
	    -t $(IMAGE_PREFIX)/$$app-web:$(IMAGE_TAG) web ; \
	done

##@ Web (Phase 4, needs Node >= 20.19 and pnpm; the images build without them)

PNPM ?= pnpm
WEB_ENV := TURBO_TELEMETRY_DISABLED=1

.PHONY: web-install
web-install: ## Install the web monorepo dependencies (pnpm, frozen lockfile)
	cd web && $(PNPM) install --frozen-lockfile

.PHONY: web-check
web-check: web-install ## Web: Prettier check, ESLint, typecheck, Vitest and production build
	cd web && $(PNPM) format:check
	cd web && $(WEB_ENV) $(PNPM) exec turbo lint typecheck test build --output-logs=errors-only

.PHONY: web-dev
web-dev: web-install ## Status page dev server; /api is proxied to STATUS_API_URL (default http://status.localtest.me)
	cd web && $(PNPM) --filter status dev

# Images are built and pulled with the engine CLI, then compose runs with --no-build. This also
# avoids compose needing Docker credential helpers when it talks to Podman.
.PHONY: compose-up
compose-up: build ## Start the services and the OTel Collector (compose)
	$(ENGINE) image inspect $(COLLECTOR_IMAGE) >/dev/null 2>&1 || $(ENGINE) pull $(COLLECTOR_IMAGE)
	$(COMPOSE) up -d --no-build --wait

.PHONY: compose-down
compose-down: ## Stop and remove the compose stack
	$(COMPOSE) down --remove-orphans

.PHONY: compose-logs
compose-logs: ## Follow the OTel Collector debug output
	$(COMPOSE) logs -f otel-collector

.PHONY: smoke
smoke: ## End-to-end check against the running compose stack
	COMPOSE="$(COMPOSE)" ./scripts/smoke.sh

##@ Local Kubernetes platform (Phase 2)

KIND ?= kind
KUBECTL ?= kubectl
HELMFILE ?= helmfile
KIND_CONFIG := deploy/kind/kind-config.yaml
CLUSTER_NAME := $(shell awk '/^name:/ {print $$2; exit}' $(KIND_CONFIG))
KUBE_CONTEXT := kind-$(CLUSTER_NAME)
CACHE_DIR := .cache

# kind uses Docker unless told otherwise; its Podman provider is experimental and needs rootful Podman.
ifeq ($(ENGINE),podman)
export KIND_EXPERIMENTAL_PROVIDER := podman
endif
# Every kubectl call (also in deploy/scripts) targets the kind context, never the current one.
KUBECTL_KIND := $(KUBECTL) --context $(KUBE_CONTEXT)
SCRIPT_ENV := KUBECTL="$(KUBECTL_KIND)"

# Host address for the gateway ports 80/443. 127.0.0.1 keeps them off the LAN. With Podman on
# macOS the ports are bound by gvproxy, an unprivileged process, and macOS only lets unprivileged
# processes bind ports below 1024 on the wildcard address, so 0.0.0.0 is the only option there
# (see deploy/README.md for the trade-off). To stay on loopback there, use host ports >= 1024:
#   make up GATEWAY_LISTEN_ADDRESS=127.0.0.1 GATEWAY_HTTP_PORT=8080 GATEWAY_HTTPS_PORT=8443
GATEWAY_HTTP_PORT ?= 80
GATEWAY_HTTPS_PORT ?= 443
ifeq ($(ENGINE)-$(shell uname -s),podman-Darwin)
GATEWAY_LISTEN_ADDRESS ?= 0.0.0.0
else
GATEWAY_LISTEN_ADDRESS ?= 127.0.0.1
endif

# Helm reads OCI registry credentials from ~/.docker/config.json as a fallback. If that file names
# a credential helper that is not installed (e.g. "credsStore": "desktop" left behind by Docker
# Desktop), every chart pull fails, even anonymous ones. Point Helm at an empty config instead.
DOCKER_CREDS_STORE := $(shell sed -n 's/.*"credsStore"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$${DOCKER_CONFIG:-$$HOME/.docker}/config.json" 2>/dev/null)
HELM_ENV :=
ifneq ($(DOCKER_CREDS_STORE),)
ifeq ($(shell command -v docker-credential-$(DOCKER_CREDS_STORE)),)
HELM_ENV := DOCKER_CONFIG=$(CURDIR)/$(CACHE_DIR)/docker-config
endif
endif

.PHONY: prereqs
prereqs: ## Check the container engine, kind, kubectl, helm, helmfile and helm-diff
	@deploy/scripts/check-prereqs.sh $(ENGINE) $(KIND_CONFIG)

.PHONY: cluster-up
cluster-up: prereqs ## Create the kind cluster (no-op if it exists)
	@if $(KIND) get clusters 2>/dev/null | grep -qx '$(CLUSTER_NAME)'; then \
	  echo "kind cluster '$(CLUSTER_NAME)' already exists"; \
	else \
	  mkdir -p $(CACHE_DIR); \
	  sed -e 's/listenAddress: "127.0.0.1"/listenAddress: "$(GATEWAY_LISTEN_ADDRESS)"/' \
	      -e 's/hostPort: 80$$/hostPort: $(GATEWAY_HTTP_PORT)/' -e 's/hostPort: 443$$/hostPort: $(GATEWAY_HTTPS_PORT)/' \
	      $(KIND_CONFIG) > $(CACHE_DIR)/kind-config.yaml; \
	  if [ "$(GATEWAY_LISTEN_ADDRESS)" != 127.0.0.1 ]; then \
	    echo "WARNING: gateway ports $(GATEWAY_HTTP_PORT)/$(GATEWAY_HTTPS_PORT) bind to $(GATEWAY_LISTEN_ADDRESS) (reachable from the network); see deploy/README.md"; \
	  fi; \
	  $(KIND) create cluster --config $(CACHE_DIR)/kind-config.yaml --wait 120s; \
	fi

.PHONY: cluster-down
cluster-down: ## Delete the kind cluster
	$(KIND) delete cluster --name $(CLUSTER_NAME)

# kind load docker-image only works with Docker. For Podman, save the images to one archive and
# load that (https://kind.sigs.k8s.io/docs/user/quick-start/#loading-an-image-into-your-cluster).
define kind_load
	@mkdir -p $(CACHE_DIR)
	@if [ "$(ENGINE)" = podman ]; then \
	  echo "podman save + kind load image-archive: $(1)"; \
	  podman save -m -o $(CACHE_DIR)/images.tar $(1) \
	    && $(KIND) load image-archive $(CACHE_DIR)/images.tar --name $(CLUSTER_NAME); \
	  rc=$$?; rm -f $(CACHE_DIR)/images.tar; exit $$rc; \
	else \
	  $(KIND) load docker-image $(1) --name $(CLUSTER_NAME); \
	fi
endef

.PHONY: images
images: build ## Build the service and web images and load them into the kind cluster
	$(call kind_load,$(SERVICE_IMAGES) $(WEB_IMAGES))

# Image for the in-cluster checks of `make verify`. Use the same Docker/Podman loader as the
# platform images, including its fallback when kind cannot import an image archive.
VERIFY_IMAGE := docker.io/curlimages/curl:8.23.0

.PHONY: verify-image
verify-image:
	@printf '%s\n' '$(VERIFY_IMAGE)' | ENGINE=$(ENGINE) KIND=$(KIND) CLUSTER_NAME=$(CLUSTER_NAME) \
	  CACHE_DIR=$(CACHE_DIR) deploy/scripts/preload-images.sh

$(CACHE_DIR)/docker-config/config.json:
	@mkdir -p $(@D) && echo '{}' > $@

.PHONY: deploy
deploy: $(CACHE_DIR)/docker-config/config.json ## Namespaces, secrets, local CA, Keycloak Operator, CoreDNS, all releases (helmfile apply), wait for SSO
	$(SCRIPT_ENV) deploy/scripts/namespaces.sh
	$(SCRIPT_ENV) deploy/scripts/grafana-admin-secret.sh
	$(SCRIPT_ENV) deploy/scripts/mkcert-ca.sh
	$(SCRIPT_ENV) deploy/scripts/identity-secrets.sh
	$(SCRIPT_ENV) deploy/scripts/keycloak-operator.sh
	$(SCRIPT_ENV) deploy/scripts/coredns-localtest.sh
	$(HELM_ENV) $(HELMFILE) --file deploy/helmfile.yaml apply --suppress-diff
	$(KUBECTL_KIND) -n envoy-gateway-system wait --for=condition=Programmed gateway/edge --timeout=300s
	$(SCRIPT_ENV) GATEWAY_HTTPS_PORT=$(GATEWAY_HTTPS_PORT) deploy/scripts/wait-identity.sh

# Third-party images referenced by the rendered releases. Images of Helm test pods and of features
# that are switched off (Envoy rate limit, Thanos sidecar) are not needed.
PLATFORM_IMAGE_REGEX := (docker\.io|quay\.io|ghcr\.io|registry\.k8s\.io)/[A-Za-z0-9./_-]+(:[A-Za-z0-9._-]+)?(@sha256:[a-f0-9]+)?
PLATFORM_IMAGE_SKIP := /bats/|/ratelimit:|/thanos:

.PHONY: platform-images
platform-images: $(CACHE_DIR)/docker-config/config.json ## Pull the stack's images with the engine (parallel) and load them into kind
	{ $(HELM_ENV) $(HELMFILE) --file deploy/helmfile.yaml template 2>/dev/null; \
	  $(KUBECTL) kustomize deploy/keycloak-operator/operator; } \
	  | grep -oE '$(PLATFORM_IMAGE_REGEX)' | grep -vE '$(PLATFORM_IMAGE_SKIP)' \
	  | ENGINE=$(ENGINE) KIND=$(KIND) CLUSTER_NAME=$(CLUSTER_NAME) CACHE_DIR=$(CACHE_DIR) deploy/scripts/preload-images.sh

.PHONY: up
up: cluster-up images platform-images deploy status ## Create the cluster, load the images and deploy everything

.PHONY: down
down: cluster-down ## Delete the cluster and everything in it

.PHONY: redeploy
redeploy: images ## Rebuild and reload the images, then restart the services
	$(KUBECTL_KIND) -n apps rollout restart deployment
	$(KUBECTL_KIND) -n apps rollout status deployment --timeout=120s

.PHONY: status
status: ## Show nodes, gateway, routes and workloads
	@$(KUBECTL_KIND) get nodes
	@echo; $(KUBECTL_KIND) get gateway,httproute -A
	@echo; $(KUBECTL_KIND) -n envoy-gateway-system get deploy,svc
	@echo; $(KUBECTL_KIND) -n apps get deploy,pods,svc,networkpolicy
	@echo; $(KUBECTL_KIND) -n observability get pods,pvc
	@echo; $(KUBECTL_KIND) -n loadgen get deploy
	@echo; $(KUBECTL_KIND) -n identity get keycloak,pods
	@echo; echo "HTTPS with the mkcert CA (trust it once: mkcert -install). Logins: make sso-users"
	@echo "Shop: https://shop.localtest.me   API (bearer token): https://api.localtest.me/orders"
	@echo "Status page: https://status.localtest.me   Grafana: https://grafana.localtest.me (Keycloak, or admin: make grafana-password)"
	@echo "SRE only: https://prometheus.localtest.me https://alertmanager.localtest.me https://mail.localtest.me (on-call inbox)"
	@echo "Keycloak: https://sso.localtest.me   Failure scenarios: make demo"

.PHONY: grafana-password
grafana-password: ## Print the generated Grafana break-glass admin password (user: admin)
	@$(KUBECTL_KIND) -n observability get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d; echo

# A separate Chrome profile resolves *.localtest.me to the gateway itself when the host DNS drops
# 127.0.0.1 answers. Trust the mkcert CA in the login keychain before opening it.
CHROME_APP ?= Google Chrome
CHROME_PROFILE ?= $(HOME)/.shd-chrome-trusted
.PHONY: browser
browser: ## Open Chrome with *.localtest.me -> 127.0.0.1 (separate profile; trust the CA first)
	@open -na "$(CHROME_APP)" --args --user-data-dir="$(CHROME_PROFILE)" \
	  --host-resolver-rules="MAP *.localtest.me 127.0.0.1" \
	  https://status.localtest.me https://shop.localtest.me

.PHONY: sso-users
sso-users: ## Print the demo logins (Keycloak realms ops and customers, Keycloak admin console)
	@s() { $(KUBECTL_KIND) -n identity get secret $$1 -o jsonpath="{.data.$$2}" | base64 -d; }; \
	printf '%-10s %-10s %-26s %s\n' REALM USER PASSWORD "USE FOR"; \
	printf '%-10s %-10s %-26s %s\n' ops sre "$$(s realm-secrets SRE_PASSWORD)" "Grafana Admin; Prometheus, Alertmanager, Mailpit, status page"; \
	printf '%-10s %-10s %-26s %s\n' ops dev "$$(s realm-secrets DEV_PASSWORD)" "Grafana Editor; status page"; \
	printf '%-10s %-10s %-26s %s\n' ops viewer "$$(s realm-secrets VIEWER_PASSWORD)" "Grafana Viewer; status page"; \
	printf '%-10s %-10s %-26s %s\n' customers customer "$$(s realm-secrets CUSTOMER_PASSWORD)" "https://shop.localtest.me (or register a new customer)"; \
	printf '%-10s %-10s %-26s %s\n' master "$$(s keycloak-admin username)" "$$(s keycloak-admin password)" "https://sso.localtest.me/admin (Keycloak admin console)"

.PHONY: load-start
load-start: ## Start the k6 load generator (steady order traffic through the gateway)
	$(KUBECTL_KIND) -n loadgen scale deployment/loadgen --replicas=1
	$(KUBECTL_KIND) -n loadgen rollout status deployment/loadgen --timeout=120s

.PHONY: load-stop
load-stop: ## Stop the k6 load generator
	$(KUBECTL_KIND) -n loadgen scale deployment/loadgen --replicas=0

.PHONY: verify
verify: verify-image ## Automated checks: platform (2), telemetry (3), visualization (4), alerting (5), identity and SSO (6)
	$(SCRIPT_ENV) GATEWAY_HTTPS_PORT=$(GATEWAY_HTTPS_PORT) CURL_IMAGE=$(VERIFY_IMAGE) deploy/scripts/verify.sh
	$(SCRIPT_ENV) GATEWAY_HTTPS_PORT=$(GATEWAY_HTTPS_PORT) deploy/scripts/verify-telemetry.sh
	$(SCRIPT_ENV) GATEWAY_HTTPS_PORT=$(GATEWAY_HTTPS_PORT) CURL_IMAGE=$(VERIFY_IMAGE) deploy/scripts/verify-status.sh
	$(SCRIPT_ENV) CURL_IMAGE=$(VERIFY_IMAGE) deploy/scripts/verify-alerting.sh
	$(SCRIPT_ENV) GATEWAY_HTTP_PORT=$(GATEWAY_HTTP_PORT) GATEWAY_HTTPS_PORT=$(GATEWAY_HTTPS_PORT) CURL_IMAGE=$(VERIFY_IMAGE) deploy/scripts/verify-identity.sh

.PHONY: demo
demo: ## Failure scenarios a-d: alerts, emails in Mailpit, inhibition, recovery (scripts/demo.sh all, ~25 min)
	KUBECTL="$(KUBECTL_KIND)" scripts/demo.sh all

.PHONY: demo-reset
demo-reset: ## Reset fault injection and scale the services back to 1
	KUBECTL="$(KUBECTL_KIND)" scripts/demo.sh reset

.PHONY: lint-charts
lint-charts: ## helm lint and render the local charts with every values file
	helm lint --strict deploy/charts/edge deploy/charts/namespace-baseline deploy/charts/observability-config deploy/charts/alerting \
	  deploy/charts/identity loadgen
	helm lint --strict deploy/charts/namespace-baseline -f deploy/values/observability-baseline.yaml
	helm lint --strict deploy/charts/namespace-baseline -f deploy/values/identity-baseline.yaml
	helm lint --strict deploy/charts/sso -f deploy/values/sso-apps.yaml
	helm lint --strict deploy/charts/sso -f deploy/values/sso-observability.yaml
	@for svc in user order payment status-api status-web shop-web; do \
	  helm lint --strict deploy/charts/microservice -f deploy/values/$$svc.yaml && \
	  helm template $$svc deploy/charts/microservice -n apps -f deploy/values/$$svc.yaml > /dev/null || exit 1; \
	done
