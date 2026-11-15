#!/usr/bin/env bash
# verify.sh — prove the sender's network policy, mounts and credentials from inside a pod that carries its labels.
# Every check states what it expects; one that cannot run is a FAIL, never an "ok".
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
NS=shock-relay POD=shock-relay-verify
QUEUE="${SHOCK_RELAY_GMAIL_DIGEST_DIR:-$HOME/.local/share/shock-relay}/gmail-digest.jsonl"
fail=0
ok()  { echo "ok    $*"; }
bad() { echo "FAIL  $*"; fail=1; }
cleanup() { kubectl -n "$NS" delete pod "$POD" --ignore-not-found --wait=false >/dev/null 2>&1; }
trap cleanup EXIT; cleanup; sleep 2

kubectl apply -f "$HERE/manifests/verify-pod.yaml" >/dev/null
if ! kubectl -n "$NS" wait --for=condition=Ready "pod/$POD" --timeout=120s >/dev/null 2>&1; then
  echo "FAIL  the verification pod did not become ready; nothing was verified"
  kubectl -n "$NS" describe pod "$POD" 2>&1 | tail -8
  exit 2
fi

probe() { # probe <expect: open|closed> <label> <host> <port>
  local expect=$1 label=$2 host=$3 port=$4 got
  got="$(kubectl -n "$NS" exec "$POD" -- python3 -c "
import socket
try:
    socket.create_connection(('$host', $port), timeout=5).close(); print('open')
except OSError:
    print('closed')" 2>/dev/null | tail -1)"
  case "$got" in
    open|closed)
      if [ "$got" = "$expect" ]; then ok "$label ($host:$port is $got)"
      else bad "$label ($host:$port is $got, expected $expect)"; fi ;;
    *) bad "$label (could not run the probe inside the pod)" ;;
  esac
}
probe open   "Gmail SMTP"                  smtp.gmail.com 465
probe open   "Gmail SMTP (STARTTLS)"       smtp.gmail.com 587
probe open   "Gmail IMAP (sent-copy check)" imap.gmail.com 993
probe closed "arbitrary internet host"     example.com 443
probe closed "other port on Gmail"         smtp.gmail.com 25
probe closed "link-local metadata"         169.254.169.254 80
probe closed "Kubernetes API"              kubernetes.default.svc 443
NODE_IP="$(kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' | awk '{print $1}')"
probe closed "host SSH (node address)"     "$NODE_IP" 22
probe closed "in-cluster registry"         10.43.0.50 5000

echo "--- no API token mounted:"
if kubectl -n "$NS" exec "$POD" -- sh -c 'test ! -e /var/run/secrets/kubernetes.io' 2>/dev/null; then ok "none"; else bad "a service-account token is mounted"; fi

echo "--- credentials and config inside the pod (booleans only, never values):"
cred="$(kubectl -n "$NS" exec "$POD" -- python3 -c "
import sys
sys.path.insert(0, '/app/services/gmail-imap')
from common import load_config
c = load_config('/etc/shock-relay/config.yaml')
print(bool(c.imap.username), bool(c.imap.password), bool(c.smtp.username), bool(c.smtp.password), bool(c.smtp.from_address), c.smtp.host)" 2>&1 | tail -1)"
if [ "$cred" = "True True True True True smtp.gmail.com" ]; then ok "the pod resolves its Gmail credentials from the Secret"
else bad "credentials did not resolve in the pod (got: ${cred:-nothing})"; fi

echo "--- the queue: readable from the pod, and a dry run leaves it untouched:"
# Producers only append, and the bug this guards against (a dry run draining the queue) only shrinks it, so compare
# entry counts rather than hashes: a producer writing during the check must not look like a failure.
queue_entries() { if [ -f "$QUEUE" ]; then grep -c . "$QUEUE" || true; else echo 0; fi; }
before="$(queue_entries)"
report="$(kubectl -n "$NS" exec "$POD" -- python3 /app/services/gmail-imap/send_digest.py --config /etc/shock-relay/config.yaml --dry-run --json 2>&1 | tail -1)"
after="$(queue_entries)"
case "$report" in *'"queued"'*) ok "the pod read the queue ($report)" ;; *) bad "the pod could not read the queue (got: ${report:-nothing})" ;; esac
if [ "$after" -ge "$before" ]; then ok "the dry run left the queue intact ($before entries before, $after after)"
else bad "the dry run removed entries from the queue ($before -> $after)"; fi
exit $fail
