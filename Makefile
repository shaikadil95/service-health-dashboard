# Service Health Dashboard. Run `make help` for targets.
# Later phases extend this file (kind cluster, Helm, demo scenarios).

SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

# Container engine: Podman if it is installed and running, otherwise Docker.
# Override with `make ENGINE=docker ...`.
ENGINE ?= $(shell podman info >/dev/null 2>&1 && echo podman || echo docker)
COMPOSE ?= $(ENGINE) compose
SERVICES := user-service order-service payment-service
IMAGE_PREFIX ?= localhost/shd
IMAGE_TAG ?= dev
COLLECTOR_IMAGE := $(shell awk '/opentelemetry-collector-contrib:/ {print $$2}' compose.yaml)

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: sync
sync: ## Install the uv workspace (all services + dev tools) into .venv
	uv sync --all-packages --locked

.PHONY: lint
lint: sync ## Lint and check formatting (ruff) and that uv.lock is up to date
	uv lock --check
	uv run ruff check .
	uv run ruff format --check .

.PHONY: fmt
fmt: sync ## Auto-fix lint findings and format the code
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: test
test: sync ## Run the unit tests
	uv run pytest

.PHONY: build
build: ## Build the service images with the container engine
	@for svc in $(SERVICES); do \
	  echo "==> $(IMAGE_PREFIX)/$$svc:$(IMAGE_TAG)"; \
	  $(ENGINE) build -f services/Dockerfile --build-arg SERVICE=$$svc \
	    -t $(IMAGE_PREFIX)/$$svc:$(IMAGE_TAG) . ; \
	done

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
