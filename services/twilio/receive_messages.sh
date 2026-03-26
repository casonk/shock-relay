#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=services/twilio/common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage: ./receive_messages.sh [--config <path>] [--to <number>] [--from <number>] [--page-size <count>] [--limit <count>] [--pretty]
EOF
}

CONFIG_FILE="$(twilio_default_config_path)"
TO_NUMBER=""
FROM_NUMBER=""
PAGE_SIZE=""
LIMIT=""
PRETTY=false

while (($#)); do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      CONFIG_FILE="$2"
      shift 2
      ;;
    --to)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      TO_NUMBER="$2"
      shift 2
      ;;
    --from)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      FROM_NUMBER="$2"
      shift 2
      ;;
    --page-size)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      PAGE_SIZE="$2"
      shift 2
      ;;
    -l|--limit)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      LIMIT="$2"
      shift 2
      ;;
    --pretty)
      PRETTY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

twilio_load_config "$CONFIG_FILE" || exit $?
if ! payload="$(twilio_list_messages_request "$TO_NUMBER" "$FROM_NUMBER" "$PAGE_SIZE")"; then
  exit 1
fi

if [[ -n "$LIMIT" ]]; then
  payload="$(printf '%s\n' "$payload" | jq -c --argjson limit "$LIMIT" '.messages |= .[:$limit]')"
fi

if [[ "$PRETTY" == "true" ]]; then
  printf '%s\n' "$payload" | jq .
else
  printf '%s\n' "$payload"
fi
