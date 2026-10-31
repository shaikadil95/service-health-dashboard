#!/usr/bin/env bash
# Makes in-cluster clients resolve *.localtest.me to the Envoy gateway Service, so that pods and the
# browser use the same URLs (needed for matching OIDC issuer URLs in Phase 6). Outside the cluster,
# public DNS already resolves *.localtest.me to 127.0.0.1, which kind maps to the gateway NodePort.
#
# Approach: add a CoreDNS `rewrite` rule to the kube-system/coredns Corefile, as described in
# https://kubernetes.io/docs/tasks/administer-cluster/dns-custom-nameservers/ and
# https://coredns.io/plugins/rewrite/ . `answer auto` rewrites the answer back to the queried name,
# so clients see an A record for api.localtest.me (no visible CNAME to the Service).
#
# Idempotent: the rule sits between marker comments and is replaced on every run; CoreDNS is only
# restarted when the Corefile actually changes. kubeadm (kind) does not reconcile this ConfigMap
# after cluster creation, so the change persists for the life of the cluster.
set -euo pipefail

KUBECTL=${KUBECTL:-kubectl}
TARGET=${GATEWAY_SERVICE_FQDN:-envoy-edge.envoy-gateway-system.svc.cluster.local}
BEGIN='# BEGIN service-health-dashboard: *.localtest.me -> gateway'
END='# END service-health-dashboard'

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# $(...) strips trailing newlines; printf adds exactly one, so the comparison below is stable.
printf '%s\n' "$($KUBECTL -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}')" >"$tmp/current"

# Drop any previous managed block, then insert the current one right after the `ready` plugin of
# the root (.:53) server block. Plugin order in the Corefile does not matter for execution (it is
# fixed at build time), but keeping the block in one place makes the diff readable.
awk -v begin="$BEGIN" -v end="$END" -v target="$TARGET" '
  index($0, begin) { skip = 1; next }
  skip && index($0, end) { skip = 0; next }
  skip { next }
  { print }
  /^[[:space:]]*ready[[:space:]]*$/ && !done {
    print "    " begin
    print "    rewrite stop {"
    print "        name regex ^(.+\\.)?localtest\\.me\\.$ " target ". answer auto"
    print "    }"
    print "    " end
    done = 1
  }
  END { if (!done) { print "no ready plugin line found in Corefile" > "/dev/stderr"; exit 1 } }
' "$tmp/current" >"$tmp/desired"

if cmp -s "$tmp/current" "$tmp/desired"; then
  echo "coredns: *.localtest.me rewrite already present (unchanged)"
  exit 0
fi

{
  echo 'data:'
  echo '  Corefile: |'
  sed 's/^/    /' "$tmp/desired"
} >"$tmp/patch.yaml"
$KUBECTL -n kube-system patch configmap coredns --type merge --patch-file "$tmp/patch.yaml" >/dev/null
# The reload plugin would pick the change up within ~1-2 min (ConfigMap sync + reload interval);
# a rollout restart applies it immediately.
$KUBECTL -n kube-system rollout restart deployment/coredns >/dev/null
$KUBECTL -n kube-system rollout status deployment/coredns --timeout=120s >/dev/null
echo "coredns: *.localtest.me -> $TARGET (configured, CoreDNS restarted)"
