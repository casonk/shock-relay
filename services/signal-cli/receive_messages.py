#!/usr/bin/env python3
import argparse
from pathlib import Path
import re
import os
import subprocess
import sys
from typing import Optional, Tuple


def extract_account_and_bus_name(config_path: str) -> Tuple[str, Optional[str]]:
    try:
        config_text = Path(config_path).read_text(encoding="utf-8")
    except OSError as e:
        raise RuntimeError(
            f"ERROR: Cannot read config file: {config_path} ({e})"
        ) from e

    lines = config_text.splitlines()
    account = ""
    bus_name = None

    in_signal_cli = False
    base_indent = None

    def val_from_line(line: str) -> str:
        # Supports: key: "value", key: 'value', key: value
        m = re.match(
            r"^\s*[^:]+:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s#]+))\s*(?:#.*)?$", line
        )
        if not m:
            return ""
        return next(v for v in m.groups() if v is not None)

    for line in lines:
        if not in_signal_cli:
            if re.match(r"^\s*signal_cli:\s*$", line):
                in_signal_cli = True
                base_indent = len(line) - len(line.lstrip())
            continue

        if line.strip() != "":
            indent = len(line) - len(line.lstrip())
            if (
                base_indent is not None
                and indent <= base_indent
                and not re.match(r"^\s*signal_cli:\s*$", line)
            ):
                break

        if re.match(r"^\s*account:\s*", line):
            account = val_from_line(line)
        elif re.match(r"^\s*bus_name:\s*", line):
            bus_name = val_from_line(line) or None

    if not account:
        raise RuntimeError("ERROR: Missing signal_cli.account in config.local.yaml")

    return account, bus_name


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
