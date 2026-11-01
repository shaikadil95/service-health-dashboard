#!/usr/bin/env bash
# Last step of `make deploy` (Phase 6): returns when single sign-on works end to end, so that
# `make up && make verify` does not race the first start of Keycloak.
#   - Keycloak Ready and both realm imports done;
#   - each realm's JWKS is served through the gateway at its public URL, from inside the cluster
#     namespace is not possible (no curl there), so from the host with the addresses pinned.
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
TIMEOUT=${TIMEOUT:-600}
# shellcheck source=edge-lib.sh
source "$(dirname "$0")/edge-lib.sh"

$KUBECTL -n identity wait --for=condition=Ready keycloak/keycloak --timeout="${TIMEOUT}s" >/dev/null
for realm in customers ops; do
  $KUBECTL -n identity wait --for=condition=Done "keycloakrealmimport/realm-$realm" --timeout="${TIMEOUT}s" >/dev/null
done
deadline=$((SECONDS + TIMEOUT))
for realm in customers ops; do
  url=$(edge_url sso.localtest.me "/realms/$realm/protocol/openid-connect/certs")
  until [[ $(edge_curl -o /dev/null -w '%{http_code}' "$url") == 200 ]]; do
    if ((SECONDS > deadline)); then
      echo "identity: $url not served after ${TIMEOUT}s" >&2
      exit 1
    fi
    sleep 5
  done
done
echo "identity: Keycloak ready, realms customers and ops served at https://sso.localtest.me"
