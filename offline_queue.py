#!/usr/bin/env python3
"""Durable at-least-once offline delivery queue backed by Differential.

The queue stores each relay send as an ``EdgeDeliveryStore`` command. A drain
worker obtains a fenced lease before invoking a provider and completes or
requeues that exact command with the lease token. A timeout after a provider
accepted a request can therefore result in a duplicate send: providers and
callers must treat this as at-least-once delivery and use their own idempotency
keys when they need exactly-once user-visible effects.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import uuid
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

COLLECTION = "shock-relay-offline-deliveries"
_LEGACY_QUEUE_NAME = "queue.jsonl"


class QueueError(Exception):
    """Raised when a persisted delivery cannot safely be processed."""


def _edge_types() -> tuple[type[Any], type[Any]]:
    """Load the reviewed Differential runtime only when queue use is requested."""

    try:
        module = import_module("differential")
        return module.EdgeDeliveryStore, module.Mutation
    except (ImportError, AttributeError) as exc:
        raise QueueError(
            "durable offline delivery requires the reviewed Differential runtime; "
            "install it before enabling the queue"
        ) from exc


def _queue_directory() -> Path:
    directory = Path(
        os.environ.get(
            "SHOCK_RELAY_QUEUE_DIR",
            Path.home() / ".local" / "share" / "shock-relay",
        )
    )
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise QueueError(f"queue directory must be a regular directory: {directory}")
    if stat.S_IMODE(directory.stat().st_mode) & 0o077:
        directory.chmod(0o700)
    return directory


def _origin_node() -> str:
    configured = os.environ.get("SHOCK_RELAY_NODE_ID", "").strip()
    return configured or f"shock-relay:{socket.gethostname()}"


def _queue_path(directory: Path) -> Path:
    return directory / "queue.sqlite3"


def _legacy_operation_id(path: Path, line_number: int, line: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"shock-relay:{path.resolve()}:{line_number}:{line}"))


def _migrate_legacy_queue(store: Any, directory: Path, origin_node: str) -> None:
    """Import the old JSONL queue idempotently before moving it aside."""

    legacy = directory / _LEGACY_QUEUE_NAME
    if not legacy.exists():
        return
    if legacy.is_symlink() or not legacy.is_file():
        raise QueueError(f"legacy queue must be a regular file: {legacy}")
    try:
        lines = legacy.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise QueueError(f"cannot read legacy queue: {legacy}") from exc
    _, mutation_type = _edge_types()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise QueueError(f"legacy queue has invalid JSON on line {line_number}") from exc
        if not isinstance(entry, dict):
            raise QueueError(f"legacy queue has invalid entry on line {line_number}")
        service, payload = entry.get("service"), entry.get("payload")
        if not isinstance(service, str) or not service.strip() or not isinstance(payload, dict):
            raise QueueError(f"legacy queue has invalid delivery on line {line_number}")
        operation_id = _legacy_operation_id(legacy, line_number, line)
        store.enqueue(
            [
                mutation_type(
                    "create",
                    COLLECTION,
                    resource_id=operation_id,
                    document={"service": service, "payload": payload},
                )
            ],
            origin_node=origin_node,
            operation_id=operation_id,
        )
    legacy.replace(directory / f"{_LEGACY_QUEUE_NAME}.migrated")


def queue_store(*, queue_dir: Path | None = None, origin_node: str | None = None) -> Any:
    """Open the local queue and import any predecessor JSONL entries once."""

    directory = queue_dir or _queue_directory()
    store_type, _ = _edge_types()
    store = store_type(_queue_path(directory))
    database = _queue_path(directory)
    if stat.S_IMODE(database.stat().st_mode) & 0o077:
        database.chmod(0o600)
    _migrate_legacy_queue(store, directory, origin_node or _origin_node())
    return store


def enqueue(
    service: str,
    payload: Mapping[str, Any],
    *,
    queue_dir: Path | None = None,
    origin_node: str | None = None,
) -> str:
    """Durably queue one provider send and return its operation ID."""

    normalized_service = str(service).strip()
    if not normalized_service or not isinstance(payload, Mapping):
        raise QueueError("service and object payload are required")
    operation_id = str(uuid.uuid4())
    node = origin_node or _origin_node()
    _, mutation_type = _edge_types()
    queue_store(queue_dir=queue_dir, origin_node=node).enqueue(
        [
            mutation_type(
                "create",
                COLLECTION,
                resource_id=operation_id,
                document={"service": normalized_service, "payload": dict(payload)},
            )
        ],
        origin_node=node,
        operation_id=operation_id,
    )
    return operation_id


def claim(
    worker_id: str,
    *,
    lease_seconds: int = 30,
    queue_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Claim one pending delivery, returning its data and required lease token."""

    raw = queue_store(queue_dir=queue_dir).claim(worker_id, lease_seconds=lease_seconds)
    if raw is None:
        return None
    mutations = raw.get("mutations")
    if not isinstance(mutations, list) or len(mutations) != 1:
        raise QueueError("queued operation does not contain exactly one delivery")
    mutation = mutations[0]
    if not isinstance(mutation, dict) or mutation.get("collection") != COLLECTION:
        raise QueueError("queued operation is not a shock-relay delivery")
    document = mutation.get("document")
    if not isinstance(document, dict):
        raise QueueError("queued delivery document is invalid")
    service, payload = document.get("service"), document.get("payload")
    if not isinstance(service, str) or not service.strip() or not isinstance(payload, dict):
        raise QueueError("queued delivery fields are invalid")
    return {
        "origin_node": raw["origin_node"],
        "operation_id": raw["operation_id"],
        "lease_token": raw["lease_token"],
        "service": service,
        "payload": payload,
    }


def complete(
    delivery: Mapping[str, Any],
    *,
    worker_id: str,
    result: Mapping[str, Any],
    queue_dir: Path | None = None,
) -> None:
    """Record successful provider handoff using the claim's lease token."""

    queue_store(queue_dir=queue_dir).complete(
        str(delivery["origin_node"]),
        str(delivery["operation_id"]),
        worker_id=worker_id,
        lease_token=str(delivery["lease_token"]),
        result=result,
    )


def fail(
    delivery: Mapping[str, Any],
    *,
    worker_id: str,
    problem: Mapping[str, Any],
    retry_after_seconds: int | None,
    queue_dir: Path | None = None,
) -> None:
    """Retry or reject a claimed delivery using the claim's lease token."""

    queue_store(queue_dir=queue_dir).fail(
        str(delivery["origin_node"]),
        str(delivery["operation_id"]),
        worker_id=worker_id,
        lease_token=str(delivery["lease_token"]),
        problem=problem,
        retry_after_seconds=retry_after_seconds,
    )
