# syntax=docker/dockerfile:1
# One Dockerfile for every Python service in the uv workspace. Build from the repository root:
#   docker build -f services/Dockerfile --build-arg SERVICE=order-service -t shd/order-service .
# Pattern: https://docs.astral.sh/uv/guides/integration/docker/ (intermediate layers in
# workspaces, non-editable install, venv copied into a clean runtime stage).

ARG PYTHON_IMAGE=docker.io/library/python:3.12-slim

FROM ${PYTHON_IMAGE} AS builder
ARG SERVICE
ARG UV_VERSION=0.13.6
RUN test -n "${SERVICE}" || (echo "--build-arg SERVICE=<dir under services/> is required" >&2; exit 1)
# uv from PyPI (glibc build) rather than COPY --from=ghcr.io/astral-sh/uv: that static musl
# binary cannot resolve DNS through the Podman machine's gvproxy resolver ("Try again").
RUN pip install --no-cache-dir --root-user-action=ignore --disable-pip-version-check \
      "uv==${UV_VERSION}"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src

# Third-party dependencies only: this layer is reused until the lockfile changes.
COPY pyproject.toml uv.lock ./
COPY services/telemetry-lib/pyproject.toml services/telemetry-lib/
COPY services/${SERVICE}/pyproject.toml services/${SERVICE}/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package "${SERVICE}"

# Workspace packages, installed as wheels (non-editable) so the source tree is not needed.
COPY services/telemetry-lib/src services/telemetry-lib/src
COPY services/${SERVICE}/src services/${SERVICE}/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package "${SERVICE}" \
 && ln -s "/app/.venv/bin/${SERVICE}" /app/.venv/bin/service

FROM ${PYTHON_IMAGE} AS runtime
ARG SERVICE
LABEL org.opencontainers.image.title="${SERVICE}" \
      org.opencontainers.image.source="https://github.com/shaikadil95/service-health-dashboard" \
      org.opencontainers.image.licenses="MIT"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent \
      --shell /usr/sbin/nologin app
# Root-owned and read-only for the app user; nothing is written at runtime, so the container
# runs with a read-only root filesystem.
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    OTEL_SEMCONV_STABILITY_OPT_IN=http
USER 10001:10001
EXPOSE 8080
# No HEALTHCHECK: Kubernetes uses /livez and /readyz probes instead.
CMD ["/app/.venv/bin/service"]
