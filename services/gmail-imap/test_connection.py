#!/usr/bin/env python3
import argparse
import json
import sys

from common import (
    ConfigError,
    MailError,
    default_config_path,
    load_config,
    test_imap_connection,
    test_smtp_connection,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Gmail IMAP and SMTP connectivity.")
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    parser.add_argument(
        "--mailbox",
        default=None,
        help="Mailbox to use for the IMAP select check. Defaults to the first configured mailbox.",
    )
    parser.add_argument("--skip-imap", action="store_true", help="Skip the IMAP login/select test.")
    parser.add_argument("--skip-smtp", action="store_true", help="Skip the SMTP login/noop test.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON response.")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    result = {}
    try:
        if not args.skip_imap:
            result["imap"] = test_imap_connection(config, mailbox=args.mailbox)
        if not args.skip_smtp:
            result["smtp"] = test_smtp_connection(config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except MailError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.pretty:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
