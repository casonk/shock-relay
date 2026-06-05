#!/usr/bin/env python3
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from offline_queue import enqueue  # noqa: E402

from common import (
    ConfigError,
    GatewayError,
    NetworkError,
    default_config_path,
    load_config,
    send_message,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a WhatsApp message via a configured HTTPS gateway."
    )
    parser.add_argument("recipient", help="Recipient identifier (e.g. whatsapp:+15551234567)")
    parser.add_argument(
        "message",
        nargs="?",
        default=os.environ.get("WHATSAPP_MESSAGE", "hello from shock-relay"),
        help="Message body. Defaults to WHATSAPP_MESSAGE or a simple test string.",
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        response = send_message(config, recipient=args.recipient, message=args.message)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except NetworkError as exc:
        if os.environ.get("SHOCK_RELAY_NO_QUEUE"):
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        entry_id = enqueue(
            "whatsapp",
            {
                "recipient": args.recipient,
                "message": args.message,
                "config": args.config,
            },
        )
        print(
            f"Offline: message queued for delivery when back online (id: {entry_id})",
            file=sys.stderr,
        )
        return 0
    except GatewayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if response.text.strip():
        print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
