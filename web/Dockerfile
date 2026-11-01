# syntax=docker/dockerfile:1
# Static web apps of the pnpm monorepo, served by unprivileged nginx. Build from web/:
#   podman build -f web/Dockerfile --build-arg APP=status -t localhost/shd/status-web:dev web
# The builder needs Node and pnpm; the runtime image only has nginx and the static files.

ARG NODE_IMAGE=docker.io/library/node:24.22.2-slim
ARG NGINX_IMAGE=docker.io/nginxinc/nginx-unprivileged:1.31.7-alpine

FROM ${NODE_IMAGE} AS build
ARG APP=status
ARG PNPM_VERSION=12.16.1
# glibc-based image: the musl resolver of Alpine-based Node images can fail behind the Podman
# machine's DNS (same issue as uv in services/Dockerfile).
RUN npm install --global --no-fund --no-audit "pnpm@${PNPM_VERSION}"
ENV CI=true TURBO_TELEMETRY_DISABLED=1
WORKDIR /src

# Dependencies first: this layer is reused until a manifest or the lockfile changes.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/${APP}/package.json apps/${APP}/
COPY packages/ui/package.json packages/ui/
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter "${APP}..."

COPY packages/ui packages/ui
COPY apps/${APP} apps/${APP}
RUN pnpm --filter "${APP}" build

FROM ${NGINX_IMAGE} AS runtime
ARG APP=status
LABEL org.opencontainers.image.title="${APP}-web" \
      org.opencontainers.image.source="https://github.com/shaikadil95/service-health-dashboard" \
      org.opencontainers.image.licenses="MIT"
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/${APP}/dist /usr/share/nginx/html
# Runs as UID 101 (nginx-unprivileged) on port 8080. With a read-only root filesystem only /tmp
# (pid file and temp paths of this image) must be writable, e.g. an emptyDir.
USER 101
EXPOSE 8080
