#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path

from common import extract_account_and_bus_name


def main() -> int:
    parser = argparse.ArgumentParser(description="Receive messages via signal-cli.")
    parser.add_argument(
        "--config",
        default=os.environ.get("SIGNAL_CLI_LOCAL_CONFIG"),
        help="Path to config.local.yaml (ignored by git). Defaults next to this script.",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=None,
        help="Seconds to wait for new messages (negative disables timeout).",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Maximum number of messages to receive before returning.",
    )
    parser.add_argument("--ignore-attachments", action="store_true")
    parser.add_argument("--ignore-stories", action="store_true")
    parser.add_argument("--ignore-avatars", action="store_true")
    parser.add_argument("--ignore-stickers", action="store_true")
    parser.add_argument("--send-read-receipts", action="store_true")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    config_path = args.config or str(script_dir / "config.local.yaml")

    account, bus_name = extract_account_and_bus_name(config_path)

    cmd = ["signal-cli", "-a", account]
    if bus_name:
        cmd.extend(["--bus-name", bus_name])
    cmd.append("receive")

    if args.timeout is not None:
        cmd.extend(["--timeout", str(args.timeout)])
    if args.max_messages is not None:
        cmd.extend(["--max-messages", str(args.max_messages)])
    if args.ignore_attachments:
        cmd.append("--ignore-attachments")
    if args.ignore_stories:
        cmd.append("--ignore-stories")
    if args.ignore_avatars:
        cmd.append("--ignore-avatars")
    if args.ignore_stickers:
        cmd.append("--ignore-stickers")
    if args.send_read_receipts:
        cmd.append("--send-read-receipts")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"signal-cli failed with exit code {e.returncode}", file=sys.stderr)
        return e.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
