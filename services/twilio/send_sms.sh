#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=services/twilio/common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage: ./send_sms.sh [--config <path>] <to_number> [message]
EOF
}

CONFIG_FILE="$(twilio_default_config_path)"
POSITIONAL=()

while (($#)); do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      CONFIG_FILE="$2"
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

TO_NUMBER="${POSITIONAL[0]}"
MESSAGE="${POSITIONAL[1]-${TWILIO_MESSAGE:-hello from shock-relay}}"

twilio_load_config "$CONFIG_FILE" || exit $?
if ! response="$(twilio_send_sms_request "$TO_NUMBER" "$MESSAGE")"; then
  exit 1
fi

if [[ -n "${response//[[:space:]]/}" ]]; then
  printf '%s\n' "$response"
fi
