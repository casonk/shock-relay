#!/usr/bin/env bash
# handover.sh pod-on|pod-off — start or suspend the CronJob. No sudo.
# The host timer and the pod must never both send: deploy.sh disables the timer before pod-on and suspends the
# pod before it enables the timer. (A queued entry is removed under a lock when it is taken, so a collision
# cannot send it twice, but it is still wrong to run both.)
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
KUBECTL="${KUBECTL:-kubectl}"
case "${1:-}" in
  pod-on)  "$KUBECTL" -n shock-relay patch cronjob shock-relay-digest -p '{"spec":{"suspend":false}}' ;;
  pod-off) "$KUBECTL" -n shock-relay patch cronjob shock-relay-digest -p '{"spec":{"suspend":true}}' ;;
  *) echo "usage: $0 pod-on|pod-off"; exit 2 ;;
esac
