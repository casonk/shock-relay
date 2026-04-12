#!/usr/bin/env python3
import argparse
import os
import socket
import sys
import time
import uuid

from common import (
    ConfigError,
    GatewayError,
    canonical_chat_id,
    chat_matches,
    default_config_path,
    get_me,
    get_updates,
    load_config,
    send_message,
    update_fingerprint,
)


def get_hostname() -> str:
    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return "unknown"


def get_ip_address() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        pass

    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a Telegram test message, wait for a reply, then send a confirmation message."
    )
    parser.add_argument(
        "chat_id",
        nargs="?",
        default=os.environ.get("TELEGRAM_TEST_CHAT_ID"),
        help="Expected chat ID for the test flow. Defaults to TELEGRAM_TEST_CHAT_ID.",
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    parser.add_argument(
        "--receive-timeout",
        type=int,
        default=int(os.environ.get("RECEIVE_TIMEOUT_SECONDS", "120")),
        help="Total seconds to wait for a reply.",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=15,
        help="Per-request long-poll timeout passed to getUpdates.",
    )
    parser.add_argument(
        "--poll-limit",
        type=int,
        default=100,
        help="Maximum number of updates to request per poll.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Sleep interval between receive attempts when getUpdates returns immediately.",
    )
    args = parser.parse_args()

    if not args.chat_id:
        parser.error("chat_id is required (or set TELEGRAM_TEST_CHAT_ID)")

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    chat_id = canonical_chat_id(args.chat_id)
    start_epoch = int(time.time())
    reg_token = f"{start_epoch}-{uuid.uuid4().hex[:6]}"
    bot_info = {}
    bot_username = ""
    try:
        bot_info = get_me(config)
        bot_username = (bot_info.get("username") or "").strip()
    except GatewayError:
        bot_info = {}

    test_payload = os.environ.get(
        "MESSAGE_TEXT_OVERRIDE", "hello from shock-relay test"
    )
    test_message_lines = [
        "shock-relay TEST",
        f"reg: {reg_token}",
        f"bot_username: @{bot_username}" if bot_username else "",
        f"computer_hostname: {get_hostname()}",
        f"computer_ip: {get_ip_address()}",
        f"test_payload: {test_payload}",
        'Please reply with any message starting with "response:" (or just reply normally).',
    ]
    test_message = "\n".join(line for line in test_message_lines if line)

    print(f"Sending TEST message (reg={reg_token}) to {args.chat_id}...")
    try:
        send_message(config, chat_id=args.chat_id, message=test_message)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except GatewayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    seen_updates = set()
    offset = None
    start = time.monotonic()
    response_update = None

    print(f"Waiting for response (timeout={args.receive_timeout}s, reg={reg_token})...")
    while True:
        elapsed = time.monotonic() - start
        remaining = args.receive_timeout - elapsed
        if remaining <= 0:
            print("ERROR: Timed out waiting for response.", file=sys.stderr)
            return 1

        request_timeout = int(min(max(1, args.poll_timeout), remaining))

        try:
            payload = get_updates(
                config,
                offset=offset,
                limit=args.poll_limit,
                timeout=request_timeout,
            )
        except GatewayError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        if payload.get("next_offset") is not None:
            offset = payload["next_offset"]

        for update in payload.get("updates", []):
            fingerprint = update_fingerprint(update)
            if fingerprint in seen_updates:
                continue
            seen_updates.add(fingerprint)

            update_chat_id = update.get("chat_id")
            text = update.get("text") or ""
            date = update.get("date")

            if not chat_matches(update_chat_id, chat_id):
                continue
            if isinstance(date, int) and date < start_epoch:
                continue
            if reg_token in text:
                continue

            response_update = update
            break

        if response_update is not None:
            break

        if request_timeout < remaining:
            time.sleep(args.poll_interval)

    confirmation_message = "\n".join(
        [
            "shock-relay CONFIRMATION",
            f"reg: {reg_token}",
            f"bot_username: @{bot_username}" if bot_username else "",
            "response_received: true",
            "",
            "response_output (truncated):",
            (response_update.get("text") or "")[:2000],
        ]
    )

    print(f"Sending CONFIRMATION back to {args.chat_id}...")
    try:
        send_message(config, chat_id=args.chat_id, message=confirmation_message)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except GatewayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
