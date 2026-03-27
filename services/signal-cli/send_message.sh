#!/usr/bin/env bash
set -euo pipefail

# Basic wrapper around `signal-cli send`.
# Usage:
#   ./send_message.sh +15557654321 "hello from Fedora"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SIGNAL_CLI_LOCAL_CONFIG:-$SCRIPT_DIR/config.local.yaml}"

# Optionally override the message via env (no secrets stored in this repo).
export SIGNAL_CLI_MESSAGE="${SIGNAL_CLI_MESSAGE:-}"

BUS_NAME=""
TO="${1:-}"
MESSAGE="${2:-${SIGNAL_CLI_MESSAGE:-hello from shock-relay}}"

if [[ -z "$TO" ]]; then
  echo "Usage: $0 <recipient_phone> [message]" >&2
  exit 2
fi

read -r ACCOUNT BUS_NAME < <(
  python3 - "$CONFIG_FILE" <<'PY'
import re
import sys

config_path = sys.argv[1]

with open(config_path, "r", encoding="utf-8") as f:
    lines = f.read().splitlines()

account = ""
bus_name = ""

in_signal_cli = False
base_indent = None

def val_from_line(line: str) -> str:
    # Supports: key: "value", key: 'value', key: value
    m = re.match(r"^\s*[^:]+:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s#]+))\s*(?:#.*)?$", line)
    if not m:
        return ""
    return next(v for v in m.groups() if v is not None)

for line in lines:
    if not in_signal_cli:
        if re.match(r"^\s*signal_cli:\s*$", line):
            in_signal_cli = True
            base_indent = len(line) - len(line.lstrip())
        continue

    # If indentation drops back to the parent block, signal_cli ended.
    if line.strip() != "":
        indent = len(line) - len(line.lstrip())
        if base_indent is not None and indent <= base_indent and not re.match(r"^\s*signal_cli:\s*$", line):
            break

    if re.match(r"^\s*account:\s*", line):
        account = val_from_line(line)
    elif re.match(r"^\s*bus_name:\s*", line):
        bus_name = val_from_line(line)

if not account:
    raise SystemExit("ERROR: Missing signal_cli.account in config.local.yaml")

sys.stdout.write(account + "\t" + bus_name)
PY
  printf '\n'
)

if [[ -n "$BUS_NAME" ]]; then
  signal-cli -a "$ACCOUNT" --bus-name "$BUS_NAME" send -m "$MESSAGE" "$TO"
else
  signal-cli -a "$ACCOUNT" send -m "$MESSAGE" "$TO"
fi

