#!/usr/bin/env python3
import argparse
import json
import sys

from common import (
    ConfigError,
    GatewayError,
    default_config_path,
    list_messages,
    load_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List Twilio SMS messages via the REST API."
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of messages to return after normalization.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=None,
        help="Twilio API PageSize query parameter.",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="Filter messages by destination phone number.",
    )
    parser.add_argument(
        "--from",
        dest="from_number",
        default=None,
        help="Filter messages by source phone number.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the normalized JSON response.",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        payload = list_messages(
            config,
            to_number=args.to,
            from_number=args.from_number,
            limit=args.limit,
            page_size=args.page_size,
        )
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except GatewayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
