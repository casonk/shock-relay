#!/usr/bin/env python3
import argparse
import os
import sys

from common import ConfigError, GatewayError, default_config_path, load_config, send_sms


def main() -> int:
    parser = argparse.ArgumentParser(description="Send an SMS message via Twilio.")
    parser.add_argument("to_number", help="Recipient phone number in E.164 format")
    parser.add_argument(
        "message",
        nargs="?",
        default=os.environ.get("TWILIO_MESSAGE", "hello from shock-relay"),
        help="Message body. Defaults to TWILIO_MESSAGE or a simple test string.",
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        response = send_sms(config, to_number=args.to_number, message=args.message)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except GatewayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if response.text.strip():
        print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
