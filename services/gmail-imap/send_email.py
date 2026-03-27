#!/usr/bin/env python3
import argparse
import json
import os
import sys

from common import ConfigError, MailError, default_config_path, load_config, send_email


def main() -> int:
    parser = argparse.ArgumentParser(description="Send an email via Gmail SMTP.")
    parser.add_argument("to_address", help="Recipient email address. Comma-separated values are allowed.")
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
        )
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except MailError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
