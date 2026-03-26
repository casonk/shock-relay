#!/usr/bin/env bash
set -euo pipefail

# Basic wrapper around `signal-cli receive`.
#
# This command blocks until messages arrive or a timeout is reached.
#
# Usage:
#   ./receive_messages.sh --timeout 60 --max-messages 5
#
# You can override the local config path via:
#   SIGNAL_CLI_LOCAL_CONFIG=/path/to/config.local.yaml ./receive_messages.sh ...

CONFIG_FILE="${SIGNAL_CLI_LOCAL_CONFIG:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.local.yaml}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "ERROR: Missing config.local.yaml at: $CONFIG_FILE" >&2
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

if [[ -n "${BUS_NAME:-}" ]]; then
  signal-cli -a "$ACCOUNT" --bus-name "$BUS_NAME" receive "$@"
else
  signal-cli -a "$ACCOUNT" receive "$@"
fi

