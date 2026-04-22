#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys

from common import (
    ConfigError,
    build_message_with_metadata,
    extract_account_and_bus_name,
    parse_metadata_args,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a Signal message via signal-cli."
    )
    parser.add_argument("recipient", help="Recipient phone number (e.g. +15551234567)")
    parser.add_argument(
        "message",
        nargs="?",
        default=os.environ.get("SIGNAL_CLI_MESSAGE", "hello from shock-relay"),
    )
    script_dir = os.path.dirname(os.path.realpath(__file__))
    parser.add_argument(
        "--config",
        default=os.environ.get(
            "SIGNAL_CLI_LOCAL_CONFIG", os.path.join(script_dir, "config.local.yaml")
        ),
        help="Path to config.local.yaml (ignored by git).",
    )
    parser.add_argument(
        "--meta",
        action="append",
        default=[],
        help="Leading Signal metadata line in 'key: value' form. May be supplied multiple times.",
    )
    args = parser.parse_args()

    config_path = args.config
    try:
        account, bus_name = extract_account_and_bus_name(config_path)
        message = build_message_with_metadata(
            args.message, parse_metadata_args(args.meta)
        )
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    cmd = ["signal-cli", "-a", account]
    if bus_name:
        cmd.extend(["--bus-name", bus_name])
    cmd.extend(["send", "-m", message, args.recipient])
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"signal-cli failed with exit code {e.returncode}", file=sys.stderr)
        return e.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
