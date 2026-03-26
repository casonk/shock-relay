#!/usr/bin/env python3
import argparse
from pathlib import Path
import os
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Signal message via signal-cli.")
    parser.add_argument("recipient", help="Recipient phone number (e.g. +15551234567)")
    parser.add_argument("message", nargs="?", default=os.environ.get("SIGNAL_CLI_MESSAGE", "hello from shock-relay"))
    script_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--config",
        default=os.environ.get("SIGNAL_CLI_LOCAL_CONFIG", str(script_dir / "config.local.yaml")),
        help="Path to config.local.yaml (ignored by git).",
    )
    args = parser.parse_args()

    config_path = args.config
    try:
        config_text = Path(config_path).read_text(encoding="utf-8")
    except OSError as e:
        print(f"ERROR: Cannot read config file: {config_path} ({e})", file=sys.stderr)
        return 2

    # Lightweight YAML extraction (avoid adding runtime deps).
    # Reads only `signal_cli.account` and optional `signal_cli.bus_name`.
    import re

    lines = config_text.splitlines()
    account = ""
    bus_name = ""
    in_signal_cli = False
    base_indent = None

    def val_from_line(line: str) -> str:
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

        if line.strip() != "":
            indent = len(line) - len(line.lstrip())
            if base_indent is not None and indent <= base_indent and not re.match(r"^\s*signal_cli:\s*$", line):
                break

        if re.match(r"^\s*account:\s*", line):
            account = val_from_line(line)
        elif re.match(r"^\s*bus_name:\s*", line):
            bus_name = val_from_line(line)

    if not account:
        print("ERROR: Missing signal_cli.account in config.local.yaml", file=sys.stderr)
        return 2

    cmd = ["signal-cli", "-a", account]
    if bus_name:
        cmd.extend(["--bus-name", bus_name])
    cmd.extend(["send", "-m", args.message, args.recipient])
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"signal-cli failed with exit code {e.returncode}", file=sys.stderr)
        return e.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

