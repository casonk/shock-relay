#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common import (
    ConfigError,
    build_message_with_metadata,
    extract_account_and_bus_name,
    parse_metadata_args,
)

from offline_queue import enqueue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Signal message via signal-cli.")
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
        message = build_message_with_metadata(args.message, parse_metadata_args(args.meta))
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    _SIGNAL_NETWORK_MARKERS = (
        "network is unreachable",
        "connection refused",
        "connection timed out",
        "name or service not known",
        "unknownhostexception",
        "connectexception",
        "failed to connect",
        "no route to host",
        "temporaryfailure",
    )

    cmd = ["signal-cli", "-a", account]
    if bus_name:
        cmd.extend(["--bus-name", bus_name])
    cmd.extend(["send", "-m", message, args.recipient])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        if result.returncode != 0:
            stderr_lower = result.stderr.lower()
            is_network = any(m in stderr_lower for m in _SIGNAL_NETWORK_MARKERS)
            if is_network and not os.environ.get("SHOCK_RELAY_NO_QUEUE"):
                payload = {
                    "recipient": args.recipient,
                    "message": args.message,
                    "config": config_path,
                }
                if args.meta:
                    payload["meta"] = args.meta
                entry_id = enqueue("signal", payload)
                print(
                    f"Offline: message queued for delivery when back online (id: {entry_id})",
                    file=sys.stderr,
                )
                return 0
            print(f"signal-cli failed with exit code {result.returncode}", file=sys.stderr)
            return result.returncode
    except FileNotFoundError:
        print("signal-cli not found in PATH", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
