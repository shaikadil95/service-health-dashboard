# shellcheck shell=bash
# Helpers for the verify scripts to call https://*.localtest.me through the gateway (Phase 6).
# Sourced, not executed. Needs KUBECTL; honours GATEWAY_HTTPS_PORT and CA_FILE.
#
#   edge_curl <curl args...>            curl with the mkcert CA, every *.localtest.me host pinned to
#                                       127.0.0.1 (independent of the host's DNS resolver)
#   edge_url <host> <path>              https://<host>[:port]<path>
#   sso_login <realm user> <url> <jar>  browser login through the gateway's OIDC filter; the
#                                       session cookies end up in <jar> (use: edge_curl -b <jar> -c <jar>)
#   client_token <realm> <client> <ns> <secret>   access token, client credentials grant

HTTPS_PORT=${GATEWAY_HTTPS_PORT:-443}
CA_FILE=${CA_FILE:-$(mkcert -CAROOT 2>/dev/null)/rootCA.pem}
EDGE_HOSTS=(api grafana prometheus alertmanager mail status shop sso home)
_EDGE_RESOLVE=()
for _h in "${EDGE_HOSTS[@]}"; do _EDGE_RESOLVE+=(--resolve "$_h.localtest.me:$HTTPS_PORT:127.0.0.1"); done
_EDGE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

edge_curl() { curl -s -m 20 --cacert "$CA_FILE" "${_EDGE_RESOLVE[@]}" "$@"; }

edge_url() {
  if [[ $HTTPS_PORT == 443 ]]; then echo "https://$1$2"; else echo "https://$1:$HTTPS_PORT$2"; fi
}

# Demo passwords live in identity/realm-secrets (deploy/scripts/identity-secrets.sh).
realm_password() { # <user>
  local key
  key="$(tr '[:lower:]' '[:upper:]' <<<"$1")_PASSWORD"
  $KUBECTL -n identity get secret realm-secrets -o jsonpath="{.data.$key}" | base64 -d
}

sso_login() { # <user> <start url> <cookie jar>
  OIDC_USERNAME=$1 OIDC_PASSWORD=$(realm_password "$1") \
    python3 "$_EDGE_DIR/oidc-login.py" --cacert "$CA_FILE" --cookie-jar "$3" "$2" >/dev/null
}

client_token() { # <realm> <client id> <namespace of its Secret> <Secret name>
  local secret
  secret=$($KUBECTL -n "$3" get secret "$4" -o jsonpath='{.data.client-secret}' | base64 -d)
  edge_curl -u "$2:$secret" -d grant_type=client_credentials \
    "$(edge_url sso.localtest.me "/realms/$1/protocol/openid-connect/token")" |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])'
}

# sso_curl <jar> <curl args with one https:// URL>: curl with the gateway session in <jar>. Envoy
# renews an expired access token with the refresh token and answers that request with a redirect to
# the same URL and the new cookies (a browser follows it transparently), so a cheap GET of a
# protected page of the host refreshes the jar first: its root, or /login on the status page, whose
# root is public (Phase 6b).
sso_curl() {
  local jar=$1 arg root=""
  shift
  for arg in "$@"; do
    if [[ $arg == https://* ]]; then
      root=$(sed -E 's#^(https://[^/]+).*#\1/#' <<<"$arg")
      [[ $root != https://status.localtest.me* ]] || root+=login
      break
    fi
  done
  [[ -z $root ]] || edge_curl -b "$jar" -c "$jar" -o /dev/null "$root" || true
  edge_curl -b "$jar" -c "$jar" "$@"
}
