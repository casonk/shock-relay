#!/usr/bin/env bash
# apply.sh — create the digest sender in K3s. No sudo. Safe to repeat.
# The namespace, volume, Secrets and network policy exist before the first job can run, and the CronJob is
# created suspended. First time on this machine: prepare-host.sh and build-image.sh come first.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
QUEUE_DIR="${SHOCK_RELAY_GMAIL_DIGEST_DIR:-$HOME/.local/share/shock-relay}"
LIVE_CONFIG="${SHOCK_RELAY_GMAIL_CONFIG:-$REPO/services/gmail-imap/config.local.yaml}"

kubectl wait --for=condition=Ready node --all --timeout=60s
kubectl get crd ciliumnetworkpolicies.cilium.io >/dev/null
[ -f "$LIVE_CONFIG" ] || { echo "no Gmail config at $LIVE_CONFIG (copy services/gmail-imap/config.example.yaml)"; exit 1; }
ctx="$(stat -c %C "$QUEUE_DIR")"
case "$ctx" in *container_file_t*) ;; *) echo "$QUEUE_DIR is labelled $ctx; run deploy/k3s/prepare-host.sh first"; exit 1 ;; esac

TZ_NAME="${SHOCK_RELAY_TZ:-$(timedatectl show -p Timezone --value 2>/dev/null || true)}"
[ -n "$TZ_NAME" ] && [ -e "/usr/share/zoneinfo/$TZ_NAME" ] || { echo "cannot tell the host timezone; set SHOCK_RELAY_TZ, e.g. America/New_York"; exit 1; }
NODE="$(kubectl get node -o jsonpath='{.items[0].metadata.name}')"

# Credentials are resolved from the vault here, on the host, into a private directory that is removed on exit;
# they reach the cluster only as a Secret, never on a command line or in a manifest.
SECRET_DIR="$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/shock-relay-k3s.XXXXXX")"; chmod 700 "$SECRET_DIR"
trap 'rm -rf "$SECRET_DIR"' EXIT
python3 -I "$HERE/make_pod_config.py" --live "$LIVE_CONFIG" --out "$SECRET_DIR"

kubectl apply -f "$HERE/manifests/00-namespace.yaml"
sed -e "s#__QUEUE_DIR__#$QUEUE_DIR#g" -e "s#__NODE__#$NODE#g" "$HERE/manifests/10-volume.yaml.tmpl" | kubectl apply -f -
kubectl -n shock-relay create secret generic shock-relay-env --from-env-file="$SECRET_DIR/env" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n shock-relay create secret generic shock-relay-config --from-file=config.yaml="$SECRET_DIR/config.yaml" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$HERE/manifests/30-network-policy.yaml"
sed "s#__TZ__#$TZ_NAME#g" "$HERE/manifests/20-cronjob.yaml" | kubectl apply -f -
echo "Deployed (the CronJob is suspended). Prove it with deploy/k3s/verify.sh, then hand over with deploy/deploy.sh --mode k3s up"
