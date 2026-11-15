#!/usr/bin/env bash
# build-image.sh — build the digest sender image and push it to the in-cluster registry (no sudo).
# Needs crew-chief's deploy/k3s/install-registry.sh once, and enable-registry-mirror.sh once as root.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
CREW_CHIEF="${CREW_CHIEF_DIR:-$REPO/../crew-chief}"
IMAGE="localhost/shock-relay-digest:k3s"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
# The pod runs what is committed; the host runs whatever is in the checkout. If they differ, a digest is
# built by different code depending on where it ran. Build only from committed code, or say so explicitly.
if [ -z "${ALLOW_DIRTY:-}" ] && [ -n "$(git -C "$REPO" status --porcelain -- services/gmail-imap)" ]; then
  echo "services/gmail-imap has uncommitted changes; the image would not match what is committed. Commit them, or set ALLOW_DIRTY=1." >&2
  exit 1
fi
mkdir -p "$WORK/services"
cp -r "$REPO/services/gmail-imap" "$WORK/services/gmail-imap"
# Local config and caches stay out of the image.
find "$WORK" \( -name '__pycache__' -o -name '*.pyc' -o -name 'config.local.*' \) -prune -exec rm -rf {} +
cp "$HERE/Containerfile" "$WORK/Containerfile"
podman build -t "$IMAGE" -f "$WORK/Containerfile" "$WORK"
"$CREW_CHIEF/deploy/k3s/push-image.sh" "$IMAGE" shock-relay-digest:k3s
echo "Next: deploy/k3s/apply.sh (the first run needs prepare-host.sh)"
