#!/usr/bin/env python3
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common import (
    ConfigError,
    GatewayError,
    NetworkError,
    default_config_path,
    load_config,
    send_message,
)

from offline_queue import enqueue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Telegram message via the Bot API.")
    parser.add_argument("chat_id", help="Telegram chat ID or @channelusername")
    parser.add_argument(
        "message",
        nargs="?",
        default=os.environ.get("TELEGRAM_MESSAGE", "hello from shock-relay"),
        help="Message body. Defaults to TELEGRAM_MESSAGE or a simple test string.",
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    parser.add_argument(
        "--parse-mode",
        default=None,
        help="Optional Telegram parse mode override (for example MarkdownV2 or HTML).",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        response = send_message(
            config,
            chat_id=args.chat_id,
            message=args.message,
            parse_mode=args.parse_mode,
        )
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except NetworkError as exc:
        if os.environ.get("SHOCK_RELAY_NO_QUEUE"):
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        payload = {
            "chat_id": args.chat_id,
            "message": args.message,
            "config": args.config,
        }
        if args.parse_mode:
            payload["parse_mode"] = args.parse_mode
        entry_id = enqueue("telegram", payload)
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
