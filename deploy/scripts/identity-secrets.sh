#!/usr/bin/env bash
# Generates the identity secrets once per cluster (`make deploy`, Phase 6) and copies each one to the
# namespaces that need it. Idempotent: existing values in identity/realm-secrets are kept, so
# re-running only re-syncs the copies. Nothing here is ever committed; `make sso-users` prints the
# demo logins.
#
#   identity/keycloak-db          PostgreSQL user for Keycloak
#   identity/keycloak-admin       bootstrap admin of Keycloak's master realm (admin console)
#   identity/realm-secrets        client secrets and demo user passwords, realm import placeholders
#   observability/grafana-oauth   Grafana's client secret (ops realm)
#   observability/ops-gateway-oidc, apps/ops-gateway-oidc   Envoy OIDC client secret (ops realm)
#   apps/shop-gateway-oidc        Envoy OIDC client secret of the shop (customers realm)
#   apps/order-service-client     client credentials of the order service (customers realm)
#   loadgen/loadgen-client        client credentials of k6 (customers realm)
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}

random() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}" || true; }
get() { # <namespace> <secret> <key>
  $KUBECTL -n "$1" get secret "$2" -o jsonpath="{.data.$3}" 2>/dev/null | base64 -d 2>/dev/null || true
}
apply_secret() { # <namespace> <name> <key=value>...
  local ns=$1 name=$2
  shift 2
  local args=()
  for kv in "$@"; do args+=(--from-literal="$kv"); done
  $KUBECTL -n "$ns" create secret generic "$name" "${args[@]}" --dry-run=client -o yaml |
    $KUBECTL apply -f - >/dev/null
  $KUBECTL -n "$ns" label secret "$name" --overwrite app.kubernetes.io/part-of=service-health-dashboard >/dev/null
}

keys=(OPS_GATEWAY_SECRET GRAFANA_SECRET SHOP_GATEWAY_SECRET ORDER_SERVICE_SECRET LOADGEN_SECRET
  CUSTOMER_PASSWORD SRE_PASSWORD DEV_PASSWORD VIEWER_PASSWORD)
pairs=()
created=0
for key in "${keys[@]}"; do
  value=$(get identity realm-secrets "$key")
  if [[ -z $value ]]; then
    value=$(random 24)
    created=1
  fi
  pairs+=("$key=$value")
  printf -v "$key" '%s' "$value"
done
apply_secret identity realm-secrets "${pairs[@]}"

db_password=$(get identity keycloak-db password)
[[ -n $db_password ]] || db_password=$(random 32)
apply_secret identity keycloak-db username=keycloak password="$db_password"

admin_password=$(get identity keycloak-admin password)
[[ -n $admin_password ]] || admin_password=$(random 24)
apply_secret identity keycloak-admin username=admin password="$admin_password"

apply_secret observability grafana-oauth client-secret="$GRAFANA_SECRET"
apply_secret observability ops-gateway-oidc client-secret="$OPS_GATEWAY_SECRET"
apply_secret apps ops-gateway-oidc client-secret="$OPS_GATEWAY_SECRET"
apply_secret apps shop-gateway-oidc client-secret="$SHOP_GATEWAY_SECRET"
apply_secret apps order-service-client client-id=order-service client-secret="$ORDER_SERVICE_SECRET"
apply_secret loadgen loadgen-client client-id=loadgen client-secret="$LOADGEN_SECRET"

if ((created)); then
  echo "identity secrets: generated (see make sso-users)"
else
  echo "identity secrets: exist (unchanged), copies synced"
fi
