#!/usr/bin/env python3
import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common import (
    ConfigError,
    MailError,
    NetworkMailError,
    default_config_path,
    load_config,
    parse_custom_header_args,
    send_email,
)

from offline_queue import enqueue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send an email via Gmail SMTP.")
    parser.add_argument(
        "to_address",
        help="Recipient email address. Comma-separated values are allowed.",
    )
    parser.add_argument("subject", help="Email subject line.")
    parser.add_argument(
        "body",
        nargs="?",
        default=os.environ.get("GMAIL_IMAP_BODY", "hello from shock-relay"),
        help="Message body. Defaults to GMAIL_IMAP_BODY or a simple test string.",
    )
    parser.add_argument(
        "--cc",
        action="append",
        default=[],
        help="Optional CC recipient. May be supplied multiple times or as a comma-separated list.",
    )
    parser.add_argument(
        "--bcc",
        action="append",
        default=[],
        help="Optional BCC recipient. May be supplied multiple times or as a comma-separated list.",
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Custom email header in 'Name: value' form. May be supplied multiple times.",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        payload = send_email(
            config,
            to_addresses=[args.to_address],
            subject=args.subject,
            body=args.body,
            cc_addresses=args.cc,
            bcc_addresses=args.bcc,
            headers=parse_custom_header_args(args.header),
        )
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except NetworkMailError as exc:
        if os.environ.get("SHOCK_RELAY_NO_QUEUE"):
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        payload = {
            "to_address": args.to_address,
            "subject": args.subject,
            "body": args.body,
            "config": args.config,
        }
        if args.cc:
            payload["cc"] = args.cc
        if args.bcc:
            payload["bcc"] = args.bcc
        if args.header:
            payload["header"] = args.header
        entry_id = enqueue("gmail", payload)
        print(
            f"Offline: message queued for delivery when back online (id: {entry_id})",
            file=sys.stderr,
        )
        return 0
    except MailError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
