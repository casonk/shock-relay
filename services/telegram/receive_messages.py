#!/usr/bin/env python3
import argparse
import json
import sys

from common import (
    ConfigError,
    GatewayError,
    default_config_path,
    get_updates,
    load_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Receive Telegram updates via the Bot API.")
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml (ignored by git).",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=None,
        help="Long-poll timeout in seconds passed to getUpdates.",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of updates to request.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=None,
        help="Telegram getUpdates offset.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the normalized JSON response.",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        payload = get_updates(
            config,
            offset=args.offset,
            limit=args.limit,
            timeout=args.timeout,
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
