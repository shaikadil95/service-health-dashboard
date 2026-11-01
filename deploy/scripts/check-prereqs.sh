#!/usr/bin/env bash
# Checks the tools and the container engine needed by `make up`. Called by `make prereqs`.
# Usage: check-prereqs.sh <engine> <kind-config>
set -euo pipefail

ENGINE=${1:?engine (docker|podman)}
KIND_CONFIG=${2:?path to kind config}
MIN_KIND=0.33.0
fail=0

ok() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$*"; }
bad() {
  printf '  \033[31mFAIL\033[0m  %s\n' "$*"
  fail=1
}

# version_ge A B: true if version A >= B (numeric dot-separated, "v" prefix ignored).
version_ge() {
  local IFS=.
  local -a a=(${1#v}) b=(${2#v})
  for i in 0 1 2; do
    ((10#${a[i]:-0} > 10#${b[i]:-0})) && return 0
    ((10#${a[i]:-0} < 10#${b[i]:-0})) && return 1
  done
  return 0
}

need() { command -v "$1" >/dev/null 2>&1 || { bad "$1 not found in PATH"; return 1; }; }

echo "Container engine: $ENGINE"
if need "$ENGINE"; then
  if ! "$ENGINE" info >/dev/null 2>&1; then
    bad "$ENGINE is installed but not reachable (is the daemon / podman machine running?)"
  elif [[ $ENGINE == podman ]]; then
    # kind's Podman provider needs rootful Podman: https://kind.sigs.k8s.io/docs/user/rootless/
    if [[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]]; then
      bad "podman runs rootless; use a rootful machine: podman machine set --rootful (machine stopped)"
    else
      ok "podman $(podman version --format '{{.Client.Version}}'), rootful, running"
    fi
    cpus=$(podman info --format '{{.Host.CPUs}}')
    mem=$(podman info --format '{{.Host.MemTotal}}')
  else
    ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"
    cpus=$(docker info --format '{{.NCPU}}')
    mem=$(docker info --format '{{.MemTotal}}')
  fi
  if [[ -n ${cpus:-} && -n ${mem:-} ]]; then
    gib=$((mem / 1024 / 1024 / 1024))
    if ((cpus < 4 || gib < 7)); then
      warn "engine VM has ${cpus} CPUs / ${gib} GiB; at least 4 CPUs / 8 GiB recommended"
    else
      ok "engine resources: ${cpus} CPUs / ${gib} GiB"
    fi
  fi
fi

if need kind; then
  v=$(kind version | awk '{print $2}')
  if version_ge "$v" "$MIN_KIND"; then ok "kind $v"; else bad "kind $v < $MIN_KIND"; fi
fi

node_image=$(awk '/image: kindest\/node:/ {print $2; exit}' "$KIND_CONFIG")
node_minor=$(sed -E 's/^kindest\/node:v1\.([0-9]+)\..*/\1/' <<<"$node_image")
if need kubectl; then
  v=$(kubectl version --client -o yaml | awk '/gitVersion/ {print $2; exit}')
  minor=$(sed -E 's/^v1\.([0-9]+)\..*/\1/' <<<"$v")
  # kubectl is supported within one minor version of the API server:
  # https://kubernetes.io/releases/version-skew-policy/#kubectl
  if ((minor >= node_minor - 1 && minor <= node_minor + 1)); then
    ok "kubectl $v (node image v1.$node_minor)"
  else
    bad "kubectl $v is outside the supported skew (±1 minor) of the node image v1.$node_minor: $(command -v kubectl)"
  fi
fi

if need helm; then
  v=$(helm version --template '{{.Version}}')
  if [[ $v == v4.* ]]; then ok "helm $v"; else bad "helm $v: Helm 4 is required"; fi
  if helm plugin list 2>/dev/null | awk '{print $1}' | grep -qx diff; then
    ok "helm-diff plugin"
  else
    bad "helm-diff plugin missing: helm plugin install https://github.com/databus23/helm-diff"
  fi
fi

if need helmfile; then ok "$(helmfile --version | head -1)"; fi

# Phase 6: the local CA for https://*.localtest.me (deploy/scripts/mkcert-ca.sh). `mkcert -install`
# (trusting it in browsers) is a one-time manual step and not checked here.
if need mkcert; then ok "mkcert $(mkcert -version 2>/dev/null) (CAROOT $(mkcert -CAROOT))"; fi

if ((fail)); then
  echo "Prerequisites missing; see deploy/README.md." >&2
  exit 1
fi
