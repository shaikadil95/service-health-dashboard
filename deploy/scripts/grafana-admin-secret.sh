#!/usr/bin/env bash
# Creates the Grafana admin Secret (observability/grafana-admin) with a random password, once per
# cluster. kube-prometheus-stack reads it through grafana.admin.existingSecret, so the chart's
# well-known default password is never used. Idempotent: an existing Secret is left unchanged.
# Show the password with `make grafana-password`.
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
NAMESPACE=observability
SECRET=grafana-admin

if $KUBECTL -n "$NAMESPACE" get secret "$SECRET" >/dev/null 2>&1; then
  echo "secret/$SECRET: exists (unchanged)"
  exit 0
fi

password=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24 || true)
if [[ ${#password} -ne 24 ]]; then
  echo "could not generate a password" >&2
  exit 1
fi
$KUBECTL -n "$NAMESPACE" create secret generic "$SECRET" \
  --from-literal=admin-user=admin \
  --from-literal=admin-password="$password" >/dev/null
$KUBECTL -n "$NAMESPACE" label secret "$SECRET" app.kubernetes.io/part-of=service-health-dashboard >/dev/null
echo "secret/$SECRET: created (user admin, random password; see make grafana-password)"
