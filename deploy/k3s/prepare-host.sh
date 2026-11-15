#!/usr/bin/env bash
# prepare-host.sh — label the digest queue folder so containers may use it. No sudo.
# SELinux keeps containers out of ordinary home-directory files; container_file_t opens exactly this folder.
# Producers on the host (CI monitors, intake) keep appending to the queue as before.
# Undo with:  restorecon -RF ~/.local/share/shock-relay
set -euo pipefail
QUEUE_DIR="${SHOCK_RELAY_GMAIL_DIGEST_DIR:-$HOME/.local/share/shock-relay}"
[ -d "$QUEUE_DIR" ] || { echo "missing $QUEUE_DIR"; exit 1; }
chcon -R -t container_file_t "$QUEUE_DIR"
echo "labelled $QUEUE_DIR: $(stat -c %C "$QUEUE_DIR")"
echo "A system-wide relabel (restorecon or an OS upgrade) would reset it; re-run this script if the pod loses access."
