#!/usr/bin/env python3
import argparse
import json
import sys
import time
import traceback

from common import (
    ConfigError,
    MailError,
    default_config_path,
    list_messages,
    load_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Gmail IMAP inbox messages.")
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    parser.add_argument(
        "--mailbox",
        action="append",
        default=[],
        help="Mailbox to scan. May be supplied multiple times. Defaults to the configured mailbox list.",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=20,
        help="Maximum number of normalized messages to return.",
    )
    parser.add_argument(
        "--unseen",
        action="store_true",
        help="Return only unseen messages.",
    )
    parser.add_argument(
        "--from-contains",
        default=None,
        help="Filter messages by sender substring.",
    )
    parser.add_argument(
        "--subject-contains",
        default=None,
        help="Filter messages by subject substring.",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Only return messages since the last N days.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Poll until at least one matching message appears, or until this timeout elapses.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Polling interval in seconds when --wait is used. Defaults to imap.poll_interval_seconds.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the normalized JSON response.",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    deadline = time.monotonic() + max(0, args.wait)
    poll_interval = (
        args.poll_interval if args.poll_interval is not None else config.imap.poll_interval_seconds
    )

    while True:
        try:
            payload = list_messages(
                config,
                mailboxes=args.mailbox or None,
                limit=args.limit,
                unseen_only=True if args.unseen else None,
                from_contains=args.from_contains,
                subject_contains=args.subject_contains,
                since_days=args.since_days,
            )
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except MailError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"ERROR: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return 1

        if payload.get("messages") or args.wait <= 0 or time.monotonic() >= deadline:
            if args.pretty:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(json.dumps(payload, sort_keys=True))
            if payload.get("messages") or args.wait <= 0:
                return 0
            print("ERROR: Timed out waiting for matching inbox messages.", file=sys.stderr)
            return 1

        time.sleep(max(1.0, float(poll_interval)))


if __name__ == "__main__":
    raise SystemExit(main())
