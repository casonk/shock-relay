#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=services/telegram/common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage: ./receive_messages.sh [--config <path>] [--timeout <seconds>] [--limit <count>] [--offset <offset>] [--pretty]
EOF
}

CONFIG_FILE="$(telegram_default_config_path)"
TIMEOUT=""
LIMIT=""
OFFSET=""
PRETTY=false

while (($#)); do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      CONFIG_FILE="$2"
      shift 2
      ;;
    -t|--timeout)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      TIMEOUT="$2"
      shift 2
      ;;
    -l|--limit)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      LIMIT="$2"
      shift 2
      ;;
    --offset)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      OFFSET="$2"
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

telegram_load_config "$CONFIG_FILE" || exit $?
if ! payload="$(telegram_get_updates_request "$OFFSET" "$LIMIT" "$TIMEOUT")"; then
  exit 1
fi

if [[ "$PRETTY" == "true" ]]; then
  printf '%s\n' "$payload" | jq .
else
  printf '%s\n' "$payload"
fi
