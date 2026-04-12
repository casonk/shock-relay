#!/usr/bin/env bash
set -euo pipefail

# End-to-end test for the signal-cli backend:
# - Send a TEST message to self (--note-to-self), including:
#   - sender linked name
#   - computer hostname + IP
# - Receive the next response message (skipping messages that contain our REG token)
# - Send a CONFIRMATION message back to self including:
#   - the REG token
#   - the received response output (truncated)
#
# Default timeouts:
# - send/receive waits up to RECEIVE_TIMEOUT_SECONDS seconds for the response
#
# Optional overrides:
# - SIGNAL_CLI_LOCAL_CONFIG=/path/to/config.local.yaml
# - RECEIVE_TIMEOUT_SECONDS=120
# - MESSAGE_TEXT_OVERRIDE="..."

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SIGNAL_CLI_LOCAL_CONFIG:-$SERVICE_DIR/config.local.yaml}"
RECEIVE_TIMEOUT_SECONDS="${RECEIVE_TIMEOUT_SECONDS:-120}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "ERROR: Missing config.local.yaml at: $CONFIG_FILE" >&2
  exit 2
fi

read -r ACCOUNT BUS_NAME LINKED_NAME < <(
  python3 - "$CONFIG_FILE" <<'PY'
import re
import sys

config_path = sys.argv[1]
txt = open(config_path, "r", encoding="utf-8").read()

def get_in_signal_cli(key: str) -> str:
    # We expect a YAML block like:
    # signal_cli:
    #   account: "+..."
    #   linked_name: "..."
    #   bus_name: "..."
    # Use a simple indentation-aware scan.
    lines = txt.splitlines()
    in_block = False
    base_indent = None
    def val_from_line(line: str) -> str:
        m = re.match(r'^\s*' + re.escape(key) + r':\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s#]+))\s*(?:#.*)?$', line)
        if not m:
            return ""
        return next(v for v in m.groups() if v is not None)

    for line in lines:
        if not in_block:
            if re.match(r'^\s*signal_cli:\s*$', line):
                in_block = True
                base_indent = len(line) - len(line.lstrip())
            continue

        # if indentation drops out of block, stop scanning
        if line.strip() != "":
            indent = len(line) - len(line.lstrip())
            if base_indent is not None and indent <= base_indent:
                break

        v = val_from_line(line)
        if v:
            return v
    return ""

account = get_in_signal_cli("account")
linked_name = get_in_signal_cli("linked_name")
bus_name = get_in_signal_cli("bus_name")

if not account:
    raise SystemExit("ERROR: Missing signal_cli.account in config.local.yaml")

sys.stdout.write(account + "\t" + (bus_name or "") + "\t" + (linked_name or ""))
PY
  printf '\n'
)

if [[ -z "$LINKED_NAME" ]]; then
  echo "ERROR: Missing signal_cli.linked_name in config.local.yaml" >&2
  exit 2
fi

HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname)"
IP_ADDR="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}' || true)"
if [[ -z "${IP_ADDR:-}" ]]; then
  IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
if [[ -z "${IP_ADDR:-}" ]]; then
  IP_ADDR="unknown"
fi

REG_TOKEN="$(date +%s)-$RANDOM"

MESSAGE_TEXT_OVERRIDE="${MESSAGE_TEXT_OVERRIDE:-}"
TEST_MESSAGE_TEXT="${MESSAGE_TEXT_OVERRIDE:-hello from shock-relay test}"

TEST_MESSAGE="$(cat <<EOF
shock-relay TEST
reg: $REG_TOKEN
sender_linked_name: $LINKED_NAME
computer_hostname: $HOSTNAME_SHORT
computer_ip: $IP_ADDR
test_payload: $TEST_MESSAGE_TEXT
Please reply with any message starting with "response:" (or just reply normally).
EOF
)"

signal_args=(-a "$ACCOUNT")
if [[ -n "${BUS_NAME:-}" ]]; then
  signal_args+=(--bus-name "$BUS_NAME")
fi

echo "Sending TEST message (reg=$REG_TOKEN) to self..."
signal-cli "${signal_args[@]}" send --note-to-self -m "$TEST_MESSAGE"

echo "Waiting for response (timeout=${RECEIVE_TIMEOUT_SECONDS}s, reg=$REG_TOKEN)..."
START_TS="$(date +%s)"
RESPONSE_RAW=""

while true; do
  NOW_TS="$(date +%s)"
  ELAPSED="$((NOW_TS - START_TS))"
  REMAINING="$((RECEIVE_TIMEOUT_SECONDS - ELAPSED))"

  if [[ "$REMAINING" -le 0 ]]; then
    echo "ERROR: Timed out waiting for response." >&2
    exit 1
  fi

  # Receive one message at a time; skip our own TEST echo using REG token match.
  OUT="$(signal-cli "${signal_args[@]}" receive --timeout "$REMAINING" --max-messages 1 \
    --ignore-attachments --ignore-stories --ignore-avatars --ignore-stickers 2>&1 || true)"

  if [[ -z "$OUT" ]]; then
    continue
  fi

  if echo "$OUT" | rg -q "reg:\\s*${REG_TOKEN}"; then
    continue
  fi

  RESPONSE_RAW="$OUT"
  break
done

RESPONSE_TRUNC="$(printf "%s" "$RESPONSE_RAW" | head -c 2000 || true)"

CONFIRMATION_MESSAGE="$(cat <<EOF
shock-relay CONFIRMATION
reg: $REG_TOKEN
sender_linked_name: $LINKED_NAME
computer_hostname: $HOSTNAME_SHORT
computer_ip: $IP_ADDR
response_received: true

response_output (truncated):
${RESPONSE_TRUNC}
EOF
)"

echo "Sending CONFIRMATION back to self..."
signal-cli "${signal_args[@]}" send --note-to-self -m "$CONFIRMATION_MESSAGE"

echo "Done."
