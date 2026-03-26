#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=services/telegram/common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage: ./test_send_receive_confirm.sh [--config <path>] [--receive-timeout <seconds>] [--poll-timeout <seconds>] [--poll-limit <count>] [--poll-interval <seconds>] <chat_id>
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

CONFIG_FILE="$(telegram_default_config_path)"
RECEIVE_TIMEOUT="${RECEIVE_TIMEOUT_SECONDS:-120}"
POLL_TIMEOUT="15"
POLL_LIMIT="100"
POLL_INTERVAL="1.0"
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
    --poll-limit)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      POLL_LIMIT="$2"
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

CHAT_ID="${POSITIONAL[0]}"
MESSAGE_TEXT_OVERRIDE="${MESSAGE_TEXT_OVERRIDE:-hello from shock-relay test}"

telegram_load_config "$CONFIG_FILE" || exit $?

START_EPOCH="$(date +%s)"
REG_TOKEN="${START_EPOCH}-$RANDOM"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname)"
IP_ADDR="$(get_ip_address)"
BOT_USERNAME="$(telegram_get_me_request 2>/dev/null | jq -r '.result.username // empty' || true)"

TEST_MESSAGE="$(cat <<EOF
shock-relay TEST
reg: $REG_TOKEN
$( [[ -n "$BOT_USERNAME" ]] && printf 'bot_username: @%s\n' "$BOT_USERNAME" )
computer_hostname: $HOSTNAME_SHORT
computer_ip: $IP_ADDR
test_payload: $MESSAGE_TEXT_OVERRIDE
Please reply with any message starting with "response:" (or just reply normally).
EOF
)"

printf 'Sending TEST message (reg=%s) to %s...\n' "$REG_TOKEN" "$CHAT_ID"
telegram_send_message_request "$CHAT_ID" "$TEST_MESSAGE" "" >/dev/null || exit 1

declare -A seen_updates=()
OFFSET=""
START_TS="$(date +%s)"
RESPONSE_UPDATE=""

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

  if ! payload="$(telegram_get_updates_request "$OFFSET" "$POLL_LIMIT" "$REQUEST_TIMEOUT")"; then
    exit 1
  fi

  next_offset="$(printf '%s\n' "$payload" | jq -r '.next_offset // empty')"
  if [[ -n "$next_offset" ]]; then
    OFFSET="$next_offset"
  fi

  while IFS= read -r update; do
    fingerprint="$(printf '%s\n' "$update" | telegram_update_fingerprint)"
    if [[ -n "${seen_updates[$fingerprint]+x}" ]]; then
      continue
    fi
    seen_updates["$fingerprint"]=1

    update_chat_id="$(printf '%s\n' "$update" | jq -r '.chat_id // empty')"
    update_text="$(printf '%s\n' "$update" | jq -r '.text // ""')"
    update_date="$(printf '%s\n' "$update" | jq -r '.date // 0')"

    if ! telegram_chat_matches "$update_chat_id" "$CHAT_ID"; then
      continue
    fi
    if [[ "$update_date" -lt "$START_EPOCH" ]]; then
      continue
    fi
    if [[ "$update_text" == *"$REG_TOKEN"* ]]; then
      continue
    fi

    RESPONSE_UPDATE="$update"
    break
  done < <(printf '%s\n' "$payload" | jq -c '.updates[]')

  if [[ -n "$RESPONSE_UPDATE" ]]; then
    break
  fi

  if [[ "$REQUEST_TIMEOUT" -lt "$REMAINING" ]]; then
    sleep "$POLL_INTERVAL"
  fi
done

RESPONSE_TEXT="$(printf '%s\n' "$RESPONSE_UPDATE" | jq -r '.text // ""' | cut -c1-2000)"
CONFIRMATION_MESSAGE="$(cat <<EOF
shock-relay CONFIRMATION
reg: $REG_TOKEN
$( [[ -n "$BOT_USERNAME" ]] && printf 'bot_username: @%s\n' "$BOT_USERNAME" )
response_received: true

response_output (truncated):
$RESPONSE_TEXT
EOF
)"

printf 'Sending CONFIRMATION back to %s...\n' "$CHAT_ID"
telegram_send_message_request "$CHAT_ID" "$CONFIRMATION_MESSAGE" "" >/dev/null || exit 1

echo "Done."
