#!/usr/bin/env python3
"""Persistent Gmail notification digest queue."""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def default_queue_file() -> Path:
    """Return the local JSONL queue path for Gmail digest notifications."""
    explicit = os.environ.get("SHOCK_RELAY_GMAIL_DIGEST_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    base = Path(
        os.environ.get(
            "SHOCK_RELAY_GMAIL_DIGEST_DIR",
            Path.home() / ".local" / "share" / "shock-relay",
        )
    ).expanduser()
    return base / "gmail-digest.jsonl"


@contextmanager
def _queue_lock(path: Path) -> Iterable[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_recipients(values: Iterable[str]) -> list[str]:
    recipients: list[str] = []
    for value in values:
        for part in str(value or "").split(","):
            cleaned = part.strip()
            if cleaned:
                recipients.append(cleaned)
    return list(dict.fromkeys(recipients))


def _normalize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in (headers or {}).items():
        name = str(key or "").strip()
        if not name:
            continue
        text = str(value or "").strip()
        if text:
            result[name] = text
    return result


def enqueue_digest(
    *,
    to_addresses: Iterable[str],
    subject: str,
    body: str,
    config_path: str = "",
    service: str = "portfolio",
    kind: str = "notification",
    headers: dict[str, str] | None = None,
    summary: str = "",
    metadata: dict[str, Any] | None = None,
    queue_file: str | Path | None = None,
) -> dict[str, Any]:
    """Append a digest notification event and return the stored entry."""
    recipients = _normalize_recipients(to_addresses)
    if not recipients:
        raise ValueError("at least one digest recipient is required")
    entry = {
        "id": str(uuid.uuid4()),
        "queued_at": _utc_timestamp(),
        "service": str(service or "portfolio").strip() or "portfolio",
        "kind": str(kind or "notification").strip() or "notification",
        "config": str(config_path or "").strip(),
        "to": recipients,
        "subject": str(subject or "").strip() or "(no subject)",
        "body": str(body or ""),
        "headers": _normalize_headers(headers),
        "summary": str(summary or "").strip(),
        "metadata": metadata or {},
    }
    append_entries([entry], queue_file=queue_file)
    return entry


def append_entries(
    entries: Iterable[dict[str, Any]], *, queue_file: str | Path | None = None
) -> None:
    """Append entries to the digest queue."""
    path = Path(queue_file).expanduser() if queue_file else default_queue_file()
    with _queue_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")


def load_entries(*, queue_file: str | Path | None = None) -> list[dict[str, Any]]:
    """Load queued digest entries without modifying the queue."""
    path = Path(queue_file).expanduser() if queue_file else default_queue_file()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with _queue_lock(path):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    entries.append(value)
    return entries


def pop_entries(
    *, queue_file: str | Path | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Atomically remove and return queued entries.

    When *limit* is supplied, entries after that limit remain in the queue.
    """
    path = Path(queue_file).expanduser() if queue_file else default_queue_file()
    if not path.exists():
        return []
    with _queue_lock(path):
        entries: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    entries.append(value)
        if limit is not None and limit > 0:
            selected = entries[:limit]
            remaining = entries[limit:]
        else:
            selected = entries
            remaining = []
        with path.open("w", encoding="utf-8") as handle:
            for entry in remaining:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return selected
