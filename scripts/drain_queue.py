#!/usr/bin/env python3
"""Drain the shock-relay offline queue.

Re-sends messages that were queued due to network failures. Safe to call
repeatedly — already-delivered messages are removed; still-failing messages
stay in the queue for the next attempt.

Usage:
    python scripts/drain_queue.py [--dry-run] [--verbose]

Exit codes:
    0  All pending entries delivered (or queue was empty).
    1  One or more entries still pending after this drain attempt.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from offline_queue import load_queue, save_queue  # noqa: E402

SERVICE_SCRIPTS = {
    "telegram": PROJECT_ROOT / "services" / "telegram" / "send_message.py",
    "whatsapp": PROJECT_ROOT / "services" / "whatsapp" / "send_message.py",
    "twilio": PROJECT_ROOT / "services" / "twilio" / "send_sms.py",
    "gmail": PROJECT_ROOT / "services" / "gmail-imap" / "send_email.py",
    "signal": PROJECT_ROOT / "services" / "signal-cli" / "send_message.py",
}


def _build_argv(entry: dict) -> list[str]:
    """Reconstruct CLI arguments from a queued payload."""
    service = entry["service"]
    p = entry["payload"]

    if service == "telegram":
        argv = [p["chat_id"], p["message"]]
        if p.get("config"):
            argv += ["--config", p["config"]]
        if p.get("parse_mode"):
            argv += ["--parse-mode", p["parse_mode"]]
        return argv

    if service == "whatsapp":
        argv = [p["recipient"], p["message"]]
        if p.get("config"):
            argv += ["--config", p["config"]]
        return argv

    if service == "twilio":
        argv = [p["to_number"], p["message"]]
        if p.get("config"):
            argv += ["--config", p["config"]]
        return argv

    if service == "gmail":
        argv = [p["to_address"], p["subject"], p["body"]]
        if p.get("config"):
            argv += ["--config", p["config"]]
        for cc in p.get("cc", []):
            argv += ["--cc", cc]
        for bcc in p.get("bcc", []):
            argv += ["--bcc", bcc]
        for hdr in p.get("header", []):
            argv += ["--header", hdr]
        return argv

    if service == "signal":
        argv = [p["recipient"], p["message"]]
        if p.get("config"):
            argv += ["--config", p["config"]]
        for m in p.get("meta", []):
            argv += ["--meta", m]
        return argv

    raise ValueError(f"Unknown service: {service!r}")


def drain(dry_run: bool = False, verbose: bool = False) -> int:
    entries = load_queue()
    if not entries:
        if verbose:
            print("Queue is empty.")
        return 0

    print(f"Draining {len(entries)} queued message(s)...")

    env = {**os.environ, "SHOCK_RELAY_NO_QUEUE": "1"}
    remaining = []
    delivered = 0
    failed = 0

    for entry in entries:
        service = entry["service"]
        script = SERVICE_SCRIPTS.get(service)
        if script is None or not script.exists():
            print(
                f"  [SKIP] Unknown service {service!r} — keeping in queue",
                file=sys.stderr,
            )
            remaining.append(entry)
            continue

        argv = _build_argv(entry)
        queued_at = entry.get("queued_at", "?")
        desc = f"{service} | queued {queued_at} | id {entry['id'][:8]}"

        if dry_run:
            print(f"  [DRY-RUN] Would send: {desc}")
            continue

        if verbose:
            print(f"  Sending: {desc}")

        result = subprocess.run(
            [sys.executable, str(script)] + argv,
            env=env,
        )

        if result.returncode == 0:
            delivered += 1
            if verbose:
                print("    -> delivered")
        else:
            failed += 1
            entry["attempts"] = entry.get("attempts", 0) + 1
            entry["last_error"] = f"exit code {result.returncode}"
            remaining.append(entry)
            if verbose:
                print(f"    -> failed (attempt #{entry['attempts']}), kept in queue")

    if not dry_run:
        save_queue(remaining)
        summary = f"Delivered: {delivered}"
        if failed:
            summary += f", still pending: {failed}"
        if remaining:
            summary += " (will retry on next drain)"
        print(summary)

    return 1 if remaining else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be sent without actually sending.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-message detail.")
    args = parser.parse_args()
    return drain(dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
