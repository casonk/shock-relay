#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=services/telegram/common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage: ./send_message.sh [--config <path>] [--parse-mode <mode>] <chat_id> [message]
EOF
}

CONFIG_FILE="$(telegram_default_config_path)"
PARSE_MODE=""
POSITIONAL=()

while (($#)); do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      CONFIG_FILE="$2"
      shift 2
      ;;
    --parse-mode)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      PARSE_MODE="$2"
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

if [[ "${#POSITIONAL[@]}" -lt 1 || "${#POSITIONAL[@]}" -gt 2 ]]; then
  usage >&2
  exit 2
fi

CHAT_ID="${POSITIONAL[0]}"
MESSAGE="${POSITIONAL[1]-${TELEGRAM_MESSAGE:-hello from shock-relay}}"

telegram_load_config "$CONFIG_FILE" || exit $?
if ! response="$(telegram_send_message_request "$CHAT_ID" "$MESSAGE" "$PARSE_MODE")"; then
  exit 1
fi

if [[ -n "${response//[[:space:]]/}" ]]; then
  printf '%s\n' "$response"
fi
