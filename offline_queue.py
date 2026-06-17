#!/usr/bin/env python3
"""Persistent offline queue for shock-relay send operations.

Messages that fail due to network errors are stored here and retried by
scripts/drain_queue.py once connectivity is restored.
"""

import contextlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def _queue_file() -> Path:
    base = Path(
        os.environ.get(
            "SHOCK_RELAY_QUEUE_DIR",
            Path.home() / ".local" / "share" / "shock-relay",
        )
    )
    base.mkdir(parents=True, exist_ok=True)
    return base / "queue.jsonl"


def enqueue(service: str, payload: dict[str, Any]) -> str:
    """Append a pending send to the queue. Returns the entry id."""
    entry = {
        "id": str(uuid.uuid4()),
        "service": service,
        "payload": payload,
        "queued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "attempts": 0,
        "last_error": None,
    }
    with _queue_file().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry["id"]


def load_queue() -> list[dict[str, Any]]:
    qf = _queue_file()
    if not qf.exists():
        return []
    entries = []
    with qf.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                with contextlib.suppress(json.JSONDecodeError):
                    entries.append(json.loads(line))
    return entries


def save_queue(entries: list[dict[str, Any]]) -> None:
    with _queue_file().open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
