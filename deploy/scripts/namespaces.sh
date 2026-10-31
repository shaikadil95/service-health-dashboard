#!/usr/bin/env bash
# Creates the platform namespaces with Pod Security Admission labels before Helm installs into them.
# Helm's --create-namespace cannot set labels, so this runs first (`make deploy`). Idempotent.
# https://kubernetes.io/docs/concepts/security/pod-security-admission/
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}

# namespace -> enforced Pod Security Standard
declare -a namespaces=(
  "apps=restricted"
  # The Envoy proxy pods meet "restricted"; the controller's cert-gen Job also does.
  "envoy-gateway-system=restricted"
)

for entry in "${namespaces[@]}"; do
  ns=${entry%%=*}
  level=${entry#*=}
  $KUBECTL create namespace "$ns" --dry-run=client -o yaml | $KUBECTL apply -f - >/dev/null
  $KUBECTL label namespace "$ns" --overwrite \
    "pod-security.kubernetes.io/enforce=$level" \
    "pod-security.kubernetes.io/warn=$level" \
    "pod-security.kubernetes.io/audit=$level" \
    "app.kubernetes.io/part-of=service-health-dashboard" >/dev/null
  echo "namespace/$ns: pod-security enforce=$level"
done
