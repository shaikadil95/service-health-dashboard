#!/usr/bin/env bash
# Pulls the third-party images of the helmfile releases with the container engine and loads them
# into the kind node (`make platform-images`, part of `make up`).
#
# Why: the kubelet pulls images one at a time (serializeImagePulls) and, with Podman, through the
# machine's flaky DNS (deploy/README.md, Troubleshooting). A fresh observability stack has ~15
# images, so first installs ran into Helm's timeout. The engine pulls them in parallel instead, and
# images already on the node are skipped, so a second run is quick.
#
# Image references are read from stdin (one per line), e.g. from `helmfile template`.
set -euo pipefail

ENGINE=${ENGINE:-docker}
KIND=${KIND:-kind}
CLUSTER_NAME=${CLUSTER_NAME:-shd}
CACHE_DIR=${CACHE_DIR:-.cache}
PARALLEL=${PARALLEL:-4}
NODE="$CLUSTER_NAME-control-plane"

# No mapfile: macOS ships bash 3.2.
images=()
while IFS= read -r line; do
  [[ -n $line ]] && images+=("$line")
done < <(sort -u)

missing=()
for image in "${images[@]}"; do
  if ! $ENGINE exec "$NODE" crictl inspecti "$image" >/dev/null 2>&1; then
    missing+=("$image")
  fi
done
echo "platform images: ${#images[@]} referenced, ${#missing[@]} not on the node yet"
[[ ${#missing[@]} -eq 0 ]] && exit 0

to_pull=()
for image in "${missing[@]}"; do
  $ENGINE image inspect "$image" >/dev/null 2>&1 || to_pull+=("$image")
done
if [[ ${#to_pull[@]} -gt 0 ]]; then
  echo "pulling ${#to_pull[@]} images with $ENGINE ($PARALLEL in parallel)"
  printf '%s\n' "${to_pull[@]}" | xargs -P "$PARALLEL" -I{} sh -c "$ENGINE pull -q '{}' >/dev/null && echo '  pulled {}'"
fi

# Same mechanism as the service images (Makefile kind_load): one archive for Podman.
mkdir -p "$CACHE_DIR"
if [[ $ENGINE == podman ]]; then
  archive="$CACHE_DIR/platform-images.tar"
  trap 'rm -f "$archive"' EXIT
  if podman save -m -o "$archive" "${missing[@]}" &&
    $KIND load image-archive "$archive" --name "$CLUSTER_NAME"; then
    loaded_by_kind=true
  else
    loaded_by_kind=false
  fi
else
  if $KIND load docker-image "${missing[@]}" --name "$CLUSTER_NAME"; then
    loaded_by_kind=true
  else
    loaded_by_kind=false
  fi
fi
if [[ $loaded_by_kind == false ]]; then
  # If kind's archive import fails, pull the same references in the node with either engine.
  # inspecti skips images that a partial import already loaded.
  echo "kind image import failed; pulling missing images into $NODE with crictl"
  export ENGINE NODE
  printf '%s\n' "${missing[@]}" | xargs -P "$PARALLEL" -I{} sh -c '
    $ENGINE exec "$NODE" crictl inspecti "$1" >/dev/null 2>&1 ||
      $ENGINE exec "$NODE" crictl pull "$1" >/dev/null
  ' sh '{}'
fi
echo "platform images: loaded ${#missing[@]} into $NODE"
