#!/usr/bin/env bash
# Makes the mkcert local CA available to the cluster (`make deploy`, Phase 6). Idempotent.
#
#   cert-manager/mkcert-ca      Secret (tls.crt + tls.key) of the CA, used by the ClusterIssuer
#                               mkcert-ca (charts/edge) to sign the *.localtest.me certificate.
#   <ns>/localtest-ca           ConfigMap with the CA certificate only (ca.crt), mounted by in-cluster
#                               clients that call https://*.localtest.me (services, Grafana, k6) and
#                               referenced by BackendTLSPolicies (Envoy -> Keycloak).
#
# The CA itself lives in mkcert's CAROOT on this machine. If it does not exist yet, it is created
# here, but NOT installed into the system and browser trust stores: run `mkcert -install` once
# yourself to trust it (https://github.com/FiloSottile/mkcert). The CA private key is copied into the
# cluster so cert-manager can sign with it; keep this cluster local (see deploy/README.md).
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
MKCERT=${MKCERT:-mkcert}
TRUST_NAMESPACES=${TRUST_NAMESPACES:-apps observability loadgen identity envoy-gateway-system}

caroot=$($MKCERT -CAROOT)
if [[ ! -f $caroot/rootCA.pem || ! -f $caroot/rootCA-key.pem ]]; then
  # mkcert creates its CA on first use. Issue a throwaway certificate to trigger that, without -install.
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  $MKCERT -cert-file "$tmp/c.pem" -key-file "$tmp/k.pem" localtest.me >/dev/null 2>&1
  echo "mkcert: created a new local CA in $caroot (not trusted yet: run 'mkcert -install' once)"
fi

$KUBECTL -n cert-manager create secret tls mkcert-ca \
  --cert="$caroot/rootCA.pem" --key="$caroot/rootCA-key.pem" --dry-run=client -o yaml |
  $KUBECTL apply -f - >/dev/null
echo "secret/mkcert-ca: cert-manager (CA from $caroot)"

for ns in $TRUST_NAMESPACES; do
  $KUBECTL -n "$ns" create configmap localtest-ca --from-file=ca.crt="$caroot/rootCA.pem" \
    --dry-run=client -o yaml | $KUBECTL apply -f - >/dev/null
done
echo "configmap/localtest-ca: $TRUST_NAMESPACES"
