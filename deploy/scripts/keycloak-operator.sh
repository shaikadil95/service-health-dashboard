#!/usr/bin/env bash
# Installs or upgrades the Keycloak Operator from its official manifests (`make deploy`, Phase 6,
# before helmfile, whose identity release creates the Keycloak and KeycloakRealmImport resources).
# The Keycloak project publishes plain manifests, no Helm chart; deploy/keycloak-operator pins the
# release and patches it with kubectl's built-in kustomize. Idempotent.
# https://www.keycloak.org/operator/installation
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
DIR=$(cd "$(dirname "$0")/../keycloak-operator" && pwd)

# Server-side apply: the CRDs are too large for client-side apply.
$KUBECTL apply --server-side --force-conflicts -k "$DIR/crds" >/dev/null
# A freshly created CRD has no status conditions for a moment, which `kubectl wait` rejects.
for _ in $(seq 1 30); do
  $KUBECTL wait --for=condition=Established --timeout=60s \
    crd/keycloaks.k8s.keycloak.org crd/keycloakrealmimports.k8s.keycloak.org \
    crd/keycloakoidcclients.k8s.keycloak.org crd/keycloaksamlclients.k8s.keycloak.org >/dev/null 2>&1 && break
  sleep 2
done
$KUBECTL apply --server-side --force-conflicts -k "$DIR/operator" >/dev/null
$KUBECTL -n identity rollout status deployment/keycloak-operator --timeout=300s >/dev/null
echo "keycloak-operator: $($KUBECTL -n identity get deployment keycloak-operator -o jsonpath='{.spec.template.spec.containers[0].image}') ready"
