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
    default_config_path,
    load_config,
    message_fingerprint,
    party_matches,
    receive_messages,
    send_message,
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
        description="Send a WhatsApp test message, wait for a reply, then send a confirmation message."
    )
    parser.add_argument(
        "recipient",
        nargs="?",
        default=os.environ.get("WHATSAPP_TEST_RECIPIENT"),
        help="Expected remote recipient/sender for the test flow. Defaults to WHATSAPP_TEST_RECIPIENT.",
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
        help="Per-request long-poll timeout passed to receive_messages.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Sleep interval between receive attempts when the gateway returns immediately.",
    )
    args = parser.parse_args()

    if not args.recipient:
        parser.error("recipient is required (or set WHATSAPP_TEST_RECIPIENT)")

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    since = str(max(0, int(time.time()) - 1))
    reg_token = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    test_payload = os.environ.get("MESSAGE_TEXT_OVERRIDE", "hello from shock-relay test")
    test_message = "\n".join(
        [
            "shock-relay TEST",
            f"reg: {reg_token}",
            f"sender: {config.sender}",
            f"computer_hostname: {get_hostname()}",
            f"computer_ip: {get_ip_address()}",
            f"test_payload: {test_payload}",
            'Please reply with any message starting with "response:" (or just reply normally).',
        ]
    )

    print(f"Sending TEST message (reg={reg_token}) to {args.recipient}...")
    try:
        send_message(config, recipient=args.recipient, message=test_message)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except GatewayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    seen_messages = set()
    cursor = None
    start = time.monotonic()
    response_message = None

    print(f"Waiting for response (timeout={args.receive_timeout}s, reg={reg_token})...")
    while True:
        elapsed = time.monotonic() - start
        remaining = args.receive_timeout - elapsed
        if remaining <= 0:
            print("ERROR: Timed out waiting for response.", file=sys.stderr)
            return 1

        request_timeout = int(min(max(1, args.poll_timeout), remaining))

        try:
            payload = receive_messages(
                config,
                limit=20,
                timeout=request_timeout,
                cursor=cursor,
                since=since,
            )
        except GatewayError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        cursor = payload.get("next_cursor") or cursor

        for message in payload.get("messages", []):
            fingerprint = message_fingerprint(message)
            if fingerprint in seen_messages:
                continue
            seen_messages.add(fingerprint)

            sender = message.get("from")
            text = message.get("text") or ""

            if reg_token in text:
                continue
            if sender and not party_matches(sender, args.recipient):
                continue

            response_message = message
            break

        if response_message is not None:
            break

        if request_timeout < remaining:
            time.sleep(args.poll_interval)

    confirmation_message = "\n".join(
        [
            "shock-relay CONFIRMATION",
            f"reg: {reg_token}",
            f"sender: {config.sender}",
            "response_received: true",
            "",
            "response_output (truncated):",
            (response_message.get("text") or "")[:2000],
        ]
    )

    print(f"Sending CONFIRMATION back to {args.recipient}...")
    try:
        send_message(config, recipient=args.recipient, message=confirmation_message)
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
