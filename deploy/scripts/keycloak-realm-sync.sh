#!/usr/bin/env bash
# Applies the Phase 6b realm settings to realms that already exist (`make deploy`, after
# wait-identity.sh). A KeycloakRealmImport only creates a realm, so on a cluster whose realms were
# imported before Phase 6b these settings would be missing; on a fresh cluster the import already set
# them and this is a no-op. Idempotent; uses kcadm.sh inside the Keycloak pod with the bootstrap admin.
# Keep the values in sync with charts/identity/realms/*.yaml (the source of truth for new realms).
#   customers: branded login theme (shd-shop), password reset with email to Mailpit
#   shop-gateway, ops-gateway, grafana: post-logout redirect to https://home.localtest.me/
# https://www.keycloak.org/docs/latest/server_admin/#the-admin-cli
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
POD=${KEYCLOAK_POD:-keycloak-0}
kc() { $KUBECTL -n identity exec "$POD" -- /opt/keycloak/bin/kcadm.sh "$@" --config /tmp/kcadm.config; }

user=$($KUBECTL -n identity get secret keycloak-admin -o jsonpath='{.data.username}' | base64 -d)
password=$($KUBECTL -n identity get secret keycloak-admin -o jsonpath='{.data.password}' | base64 -d)
kc config credentials --server http://localhost:8080 --realm master --user "$user" --password "$password" >/dev/null 2>&1 ||
  { echo "keycloak-realm-sync: admin login failed" >&2; exit 1; }

kc update realms/customers -s loginTheme=shd-shop -s resetPasswordAllowed=true \
  -s smtpServer.host=mailpit.observability.svc -s smtpServer.port=1025 \
  -s smtpServer.from=shop@shd.localtest.me -s 'smtpServer.fromDisplayName=Service Health Shop'

post_logout() { # <realm> <client id> <post.logout.redirect.uris>
  local id
  id=$(kc get clients -r "$1" -q clientId="$2" --fields id --format csv --noquotes)
  [[ -n $id ]] || { echo "keycloak-realm-sync: client $2 not found in realm $1" >&2; return 1; }
  kc update "clients/$id" -r "$1" -s "attributes.\"post.logout.redirect.uris\"=$3"
}
post_logout customers shop-gateway 'https://home.localtest.me/*##https://shop.localtest.me/*'
post_logout ops ops-gateway 'https://home.localtest.me/*'
post_logout ops grafana 'https://home.localtest.me/*##https://grafana.localtest.me/login'

$KUBECTL -n identity exec "$POD" -- rm -f /tmp/kcadm.config
echo "keycloak-realm-sync: customers login theme shd-shop, post-logout redirects to https://home.localtest.me"
