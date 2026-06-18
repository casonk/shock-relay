#!/usr/bin/env python3
"""Send queued Gmail notification digests."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
loaded_common = sys.modules.get("common")
loaded_common_path = Path(str(getattr(loaded_common, "__file__", ""))).resolve()
if loaded_common is not None and loaded_common_path.parent != SCRIPT_DIR:
    sys.modules.pop("common", None)
if str(SCRIPT_DIR) in sys.path:
    sys.path.remove(str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from common import ConfigError, MailError, default_config_path, load_config, send_email
from digest_queue import append_entries, default_queue_file, pop_entries

_DIGEST_HEADERS = {
    "X-Portfolio-Service": "shock-relay",
    "X-Crew-Chief-Intent": "digest",
    "X-Shock-Relay-Digest": "gmail",
}


def _entry_config(entry: dict[str, Any], default_config: str) -> str:
    return str(entry.get("config") or default_config).strip()


def _entry_recipients(entry: dict[str, Any]) -> tuple[str, ...]:
    raw_recipients = entry.get("to")
    if isinstance(raw_recipients, list):
        values = raw_recipients
    else:
        values = [raw_recipients]
    recipients: list[str] = []
    for value in values:
        for part in str(value or "").split(","):
            cleaned = part.strip()
            if cleaned:
                recipients.append(cleaned)
    return tuple(dict.fromkeys(recipients))


def _group_entries(
    entries: list[dict[str, Any]], *, default_config: str
) -> dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]]:
    groups: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        recipients = _entry_recipients(entry)
        if not recipients:
            continue
        groups[(_entry_config(entry, default_config), recipients)].append(entry)
    return dict(groups)


def _service_counts(entries: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for entry in entries:
        service = str(entry.get("service") or "portfolio").strip() or "portfolio"
        counts[service] = counts.get(service, 0) + 1
    return ", ".join(f"{service}: {count}" for service, count in sorted(counts.items()))


def build_digest_subject(entries: list[dict[str, Any]], *, subject_prefix: str) -> str:
    count = len(entries)
    plural = "" if count == 1 else "s"
    counts = _service_counts(entries)
    suffix = f" ({counts})" if counts else ""
    return f"{subject_prefix}: {count} notification{plural}{suffix}"


def build_digest_body(entries: list[dict[str, Any]]) -> str:
    lines = [
        "Notification digest",
        f"Queued item count: {len(entries)}",
        f"Sources: {_service_counts(entries) or 'none'}",
        "",
    ]
    by_source: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        service = str(entry.get("service") or "portfolio").strip() or "portfolio"
        kind = str(entry.get("kind") or "notification").strip() or "notification"
        by_source[(service, kind)].append(entry)

    for (service, kind), group in sorted(by_source.items()):
        lines.append(f"## {service} / {kind} ({len(group)})")
        for index, entry in enumerate(group, start=1):
            queued_at = str(entry.get("queued_at") or "?")
            subject = str(entry.get("subject") or "(no subject)")
            summary = str(entry.get("summary") or "").strip()
            body = str(entry.get("body") or "").strip()
            lines.append(f"{index}. [{queued_at}] {summary or subject}")
            if summary and summary != subject:
                lines.append(f"   Subject: {subject}")
            if body:
                for body_line in body.splitlines():
                    lines.append(f"   {body_line}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def send_queued_digest(
    *,
    default_config: str,
    queue_file: str | Path | None = None,
    subject_prefix: str = "[portfolio] Digest",
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    entries = pop_entries(queue_file=queue_file, limit=limit)
    result: dict[str, Any] = {
        "queued": len(entries),
        "sent_digests": 0,
        "requeued": 0,
        "errors": [],
    }
    if not entries:
        return result

    groups = _group_entries(entries, default_config=default_config)
    skipped = [entry for entry in entries if not _entry_recipients(entry)]
    if skipped:
        result["errors"].append(f"skipped {len(skipped)} entrie(s) without recipients")

    for (config_path, recipients), group in groups.items():
        subject = build_digest_subject(group, subject_prefix=subject_prefix)
        body = build_digest_body(group)
        if dry_run:
            print(
                json.dumps(
                    {
                        "config": config_path,
                        "to": list(recipients),
                        "subject": subject,
                        "count": len(group),
                    },
                    sort_keys=True,
                )
            )
            continue
        try:
            config = load_config(config_path)
            send_email(
                config,
                to_addresses=list(recipients),
                subject=subject,
                body=body,
                headers=_DIGEST_HEADERS,
            )
        except Exception as exc:  # noqa: BLE001
            append_entries(group, queue_file=queue_file)
            result["requeued"] += len(group)
            result["errors"].append(
                f"failed sending digest to {', '.join(recipients)}: {type(exc).__name__}: {exc}"
            )
            continue
        result["sent_digests"] += 1

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Default config.local.yaml path for queued items missing a config.",
    )
    parser.add_argument(
        "--queue-file",
        default=str(default_queue_file()),
        help="Digest queue JSONL path.",
    )
    parser.add_argument(
        "--subject-prefix",
        default=os.environ.get("SHOCK_RELAY_GMAIL_DIGEST_SUBJECT_PREFIX", "[portfolio] Digest"),
        help="Subject prefix for aggregate digest emails.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximum queued items to drain.")
    parser.add_argument("--dry-run", action="store_true", help="Show digests without sending.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON summary.")
    args = parser.parse_args()

    try:
        result = send_queued_digest(
            default_config=args.config,
            queue_file=args.queue_file,
            subject_prefix=args.subject_prefix,
            dry_run=args.dry_run,
            limit=args.limit or None,
        )
    except (ConfigError, MailError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            "Gmail digest: "
            f"queued={result['queued']} "
            f"sent={result['sent_digests']} "
            f"requeued={result['requeued']}"
        )
        for error in result["errors"]:
            print(f"WARNING: {error}", file=sys.stderr)
    return 1 if result["errors"] and result["requeued"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
