#!/usr/bin/env python3
"""Queue a Gmail notification for the next digest send."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
loaded_common = sys.modules.get("common")
loaded_common_path = Path(str(getattr(loaded_common, "__file__", ""))).resolve()
if loaded_common is not None and loaded_common_path.parent != SCRIPT_DIR:
    sys.modules.pop("common", None)
if str(SCRIPT_DIR) in sys.path:
    sys.path.remove(str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from common import ConfigError, default_config_path, parse_custom_header_args
from digest_queue import enqueue_digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "to_address",
        help="Recipient email address. Comma-separated values are allowed.",
    )
    parser.add_argument("subject", help="Original notification subject.")
    parser.add_argument(
        "body",
        nargs="?",
        default=os.environ.get("GMAIL_IMAP_BODY", ""),
        help="Original notification body. Defaults to GMAIL_IMAP_BODY.",
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to config.local.yaml for the eventual digest send.",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Custom original header in 'Name: value' form. May be supplied multiple times.",
    )
    parser.add_argument("--service", default="portfolio", help="Source service name.")
    parser.add_argument("--kind", default="notification", help="Source notification kind.")
    parser.add_argument("--summary", default="", help="Short summary for the digest list.")
    parser.add_argument("--queue-file", default="", help="Override the digest queue path.")
    args = parser.parse_args()

    try:
        entry = enqueue_digest(
            to_addresses=[args.to_address],
            subject=args.subject,
            body=args.body,
            config_path=args.config,
            service=args.service,
            kind=args.kind,
            headers=parse_custom_header_args(args.header),
            summary=args.summary,
            queue_file=args.queue_file or None,
        )
    except (ConfigError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    print(json.dumps({"queued": True, "id": entry["id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
