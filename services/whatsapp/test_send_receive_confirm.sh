#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=services/whatsapp/common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage: ./test_send_receive_confirm.sh [--config <path>] [--receive-timeout <seconds>] [--poll-timeout <seconds>] [--poll-interval <seconds>] <recipient>
EOF
}

get_ip_address() {
  local ip_addr=""
  ip_addr="$(ip -4 route get 1.1.1.1 2>/dev/null | awk "{print \$7; exit}" || true)"
  if [[ -z "$ip_addr" ]]; then
    ip_addr="$(hostname -I 2>/dev/null | awk "{print \$1; exit}" || true)"
  fi
  if [[ -z "$ip_addr" ]]; then
    ip_addr="unknown"
  fi
  printf '%s\n' "$ip_addr"
}

CONFIG_FILE="$(whatsapp_default_config_path)"
RECEIVE_TIMEOUT="${RECEIVE_TIMEOUT_SECONDS:-120}"
POLL_TIMEOUT="15"
POLL_INTERVAL="2.0"
POSITIONAL=()

while (($#)); do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      CONFIG_FILE="$2"
      shift 2
      ;;
    --receive-timeout)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      RECEIVE_TIMEOUT="$2"
      shift 2
      ;;
    --poll-timeout)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      POLL_TIMEOUT="$2"
      shift 2
      ;;
    --poll-interval)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      POLL_INTERVAL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while (($#)); do
        POSITIONAL+=("$1")
        shift
      done
      ;;
    -*)
      usage >&2
      exit 2
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [[ "${#POSITIONAL[@]}" -ne 1 ]]; then
  usage >&2
  exit 2
fi

RECIPIENT="${POSITIONAL[0]}"
MESSAGE_TEXT_OVERRIDE="${MESSAGE_TEXT_OVERRIDE:-hello from shock-relay test}"

whatsapp_load_config "$CONFIG_FILE" || exit $?

SINCE="$(( $(date +%s) - 1 ))"
if [[ "$SINCE" -lt 0 ]]; then
  SINCE="0"
fi

REG_TOKEN="$(date +%s)-$RANDOM"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname)"
IP_ADDR="$(get_ip_address)"

TEST_MESSAGE="$(cat <<EOF
shock-relay TEST
reg: $REG_TOKEN
sender: $WHATSAPP_SENDER
computer_hostname: $HOSTNAME_SHORT
computer_ip: $IP_ADDR
test_payload: $MESSAGE_TEXT_OVERRIDE
Please reply with any message starting with "response:" (or just reply normally).
EOF
)"

printf 'Sending TEST message (reg=%s) to %s...\n' "$REG_TOKEN" "$RECIPIENT"
whatsapp_send_message_request "$RECIPIENT" "$TEST_MESSAGE" >/dev/null || exit 1

declare -A seen_messages=()
CURSOR=""
START_TS="$(date +%s)"
RESPONSE_MESSAGE=""

printf 'Waiting for response (timeout=%ss, reg=%s)...\n' "$RECEIVE_TIMEOUT" "$REG_TOKEN"
while true; do
  NOW_TS="$(date +%s)"
  ELAPSED="$((NOW_TS - START_TS))"
  REMAINING="$((RECEIVE_TIMEOUT - ELAPSED))"
  if [[ "$REMAINING" -le 0 ]]; then
    echo "ERROR: Timed out waiting for response." >&2
    exit 1
  fi

  REQUEST_TIMEOUT="$POLL_TIMEOUT"
  if [[ "$REQUEST_TIMEOUT" -lt 1 ]]; then
    REQUEST_TIMEOUT=1
  fi
  if [[ "$REQUEST_TIMEOUT" -gt "$REMAINING" ]]; then
    REQUEST_TIMEOUT="$REMAINING"
  fi

  if ! payload="$(whatsapp_receive_messages_request "20" "$REQUEST_TIMEOUT" "$CURSOR" "$SINCE")"; then
    exit 1
  fi

  next_cursor="$(printf '%s\n' "$payload" | jq -r '.next_cursor // empty')"
  if [[ -n "$next_cursor" ]]; then
    CURSOR="$next_cursor"
  fi

  while IFS= read -r message; do
    fingerprint="$(printf '%s\n' "$message" | whatsapp_message_fingerprint)"
    if [[ -n "${seen_messages[$fingerprint]+x}" ]]; then
      continue
    fi
    seen_messages["$fingerprint"]=1

    sender="$(printf '%s\n' "$message" | jq -r '.from // empty')"
    text="$(printf '%s\n' "$message" | jq -r '.text // ""')"

    if [[ "$text" == *"$REG_TOKEN"* ]]; then
      continue
    fi
    if [[ -n "$sender" ]] && ! whatsapp_party_matches "$sender" "$RECIPIENT"; then
      continue
    fi

    RESPONSE_MESSAGE="$message"
    break
  done < <(printf '%s\n' "$payload" | jq -c '.messages[]')

  if [[ -n "$RESPONSE_MESSAGE" ]]; then
    break
  fi

  if [[ "$REQUEST_TIMEOUT" -lt "$REMAINING" ]]; then
    sleep "$POLL_INTERVAL"
  fi
done

RESPONSE_TEXT="$(printf '%s\n' "$RESPONSE_MESSAGE" | jq -r '.text // ""' | cut -c1-2000)"
CONFIRMATION_MESSAGE="$(cat <<EOF
shock-relay CONFIRMATION
reg: $REG_TOKEN
sender: $WHATSAPP_SENDER
response_received: true

response_output (truncated):
$RESPONSE_TEXT
EOF
)"

printf 'Sending CONFIRMATION back to %s...\n' "$RECIPIENT"
whatsapp_send_message_request "$RECIPIENT" "$CONFIRMATION_MESSAGE" >/dev/null || exit 1

echo "Done."
