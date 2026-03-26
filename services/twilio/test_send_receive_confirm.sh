#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=services/twilio/common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage: ./test_send_receive_confirm.sh [--config <path>] [--receive-timeout <seconds>] [--poll-interval <seconds>] [--poll-page-size <count>] <recipient>
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

CONFIG_FILE="$(twilio_default_config_path)"
RECEIVE_TIMEOUT="${RECEIVE_TIMEOUT_SECONDS:-120}"
POLL_INTERVAL="2.0"
POLL_PAGE_SIZE="50"
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
    --poll-interval)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      POLL_INTERVAL="$2"
      shift 2
      ;;
    --poll-page-size)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      POLL_PAGE_SIZE="$2"
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

twilio_load_config "$CONFIG_FILE" || exit $?

REG_TOKEN="$(date +%s)-$RANDOM"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname)"
IP_ADDR="$(get_ip_address)"
TEST_MESSAGE="$(cat <<EOF
shock-relay TEST
reg: $REG_TOKEN
sender: $TWILIO_FROM_PHONE
computer_hostname: $HOSTNAME_SHORT
computer_ip: $IP_ADDR
test_payload: $MESSAGE_TEXT_OVERRIDE
Please reply with any message starting with "response:" (or just reply normally).
EOF
)"

printf 'Sending TEST message (reg=%s) to %s...\n' "$REG_TOKEN" "$RECIPIENT"
if ! baseline_payload="$(twilio_list_messages_request "$TWILIO_FROM_PHONE" "$RECIPIENT" "$POLL_PAGE_SIZE")"; then
  exit 1
fi
twilio_send_sms_request "$RECIPIENT" "$TEST_MESSAGE" >/dev/null || exit 1

declare -A seen_messages=()
while IFS= read -r message; do
  fingerprint="$(printf '%s\n' "$message" | twilio_message_fingerprint)"
  seen_messages["$fingerprint"]=1
done < <(printf '%s\n' "$baseline_payload" | jq -c '.messages[]')

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

  if ! payload="$(twilio_list_messages_request "$TWILIO_FROM_PHONE" "$RECIPIENT" "$POLL_PAGE_SIZE")"; then
    exit 1
  fi

  while IFS= read -r message; do
    fingerprint="$(printf '%s\n' "$message" | twilio_message_fingerprint)"
    if [[ -n "${seen_messages[$fingerprint]+x}" ]]; then
      continue
    fi
    seen_messages["$fingerprint"]=1

    body="$(printf '%s\n' "$message" | jq -r '.body // ""')"
    from_number="$(printf '%s\n' "$message" | jq -r '.from // ""')"

    if [[ "$body" == *"$REG_TOKEN"* ]]; then
      continue
    fi
    if [[ -n "$from_number" ]] && ! twilio_phone_matches "$from_number" "$RECIPIENT"; then
      continue
    fi

    RESPONSE_MESSAGE="$message"
    break
  done < <(printf '%s\n' "$payload" | jq -c '.messages[]')

  if [[ -n "$RESPONSE_MESSAGE" ]]; then
    break
  fi

  sleep "$POLL_INTERVAL"
done

RESPONSE_TEXT="$(printf '%s\n' "$RESPONSE_MESSAGE" | jq -r '.body // ""' | cut -c1-2000)"
CONFIRMATION_MESSAGE="$(cat <<EOF
shock-relay CONFIRMATION
reg: $REG_TOKEN
sender: $TWILIO_FROM_PHONE
response_received: true

response_output (truncated):
$RESPONSE_TEXT
EOF
)"

printf 'Sending CONFIRMATION back to %s...\n' "$RECIPIENT"
twilio_send_sms_request "$RECIPIENT" "$CONFIRMATION_MESSAGE" >/dev/null || exit 1

echo "Done."
