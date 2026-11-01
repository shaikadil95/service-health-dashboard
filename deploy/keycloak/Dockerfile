# syntax=docker/dockerfile:1
# Keycloak with the customers realm's login theme (web/apps/keycloak-theme, Keycloakify), pre-built
# ("optimized") for the options the Keycloak Operator sets. Build context is the pnpm monorepo web/:
#   podman build -f deploy/keycloak/Dockerfile -t localhost/shd/keycloak:dev web
# https://www.keycloak.org/server/containers

ARG NODE_IMAGE=docker.io/library/node:24.22.2-slim
ARG MAVEN_IMAGE=docker.io/library/maven:3.9.16-eclipse-temurin-21
ARG KEYCLOAK_IMAGE=quay.io/keycloak/keycloak:26.8.1

FROM ${MAVEN_IMAGE} AS maven

# 1. Theme JAR: Keycloakify runs after the Vite build and packages the theme with Maven (needs a
# JDK). glibc-based Node image: the musl resolver of Alpine-based images can fail behind the
# Podman machine's DNS (see web/Dockerfile). JDK and Maven come from the official Maven image.
FROM ${NODE_IMAGE} AS theme
ARG PNPM_VERSION=12.16.1
COPY --from=maven /opt/java/openjdk /opt/java/openjdk
COPY --from=maven /usr/share/maven /usr/share/maven
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:/usr/share/maven/bin:$PATH \
    CI=true TURBO_TELEMETRY_DISABLED=1
RUN npm install --global --no-fund --no-audit "pnpm@${PNPM_VERSION}"
WORKDIR /src

# Dependencies first: this layer is reused until a manifest or the lockfile changes.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/keycloak-theme/package.json apps/keycloak-theme/
COPY packages/ui/package.json packages/ui/
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter "keycloak-theme..."

COPY packages/ui packages/ui
COPY apps/keycloak-theme apps/keycloak-theme
# The Maven cache keeps the plugins of the pom.xml that Keycloakify generates.
RUN --mount=type=cache,id=keycloakify-m2,target=/root/.m2 \
    pnpm --filter keycloak-theme build-keycloak-theme

# 2. Optimized server build. The Keycloak Operator starts custom images with `start --optimized`,
# so the build-time options must equal the ones it sets at runtime (deploy/charts/identity/
# templates/keycloak.yaml). These are the build-time options of `kc.sh build --help-all` (26.8.1)
# among them; the rest (hostname, proxy headers, http, cache, metrics histograms, event list,
# tracing endpoint/ratio, telemetry attributes) are runtime options and stay with the operator.
FROM ${KEYCLOAK_IMAGE} AS builder
ENV KC_DB=postgres \
    KC_FEATURES=user-event-metrics \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_EVENT_METRICS_USER_ENABLED=true \
    KC_TRACING_ENABLED=true \
    KC_TRACING_SAMPLER_TYPE=parentbased_traceidratio
# Keycloakify's JAR for Keycloak >= 26 (vite.config.ts: keycloakVersionTargets).
COPY --from=theme \
    /src/apps/keycloak-theme/dist_keycloak/keycloak-theme-for-kc-all-other-versions.jar \
    /opt/keycloak/providers/shd-shop-theme.jar
RUN /opt/keycloak/bin/kc.sh build

# 3. Runtime: the base image plus the built server; no Node, Maven or build-time ENV.
FROM ${KEYCLOAK_IMAGE}
LABEL org.opencontainers.image.title="keycloak" \
      org.opencontainers.image.description="Keycloak with the shd-shop login theme, optimized build" \
      org.opencontainers.image.source="https://github.com/shaikadil95/service-health-dashboard" \
      org.opencontainers.image.licenses="MIT"
COPY --from=builder /opt/keycloak/ /opt/keycloak/
USER 1000
