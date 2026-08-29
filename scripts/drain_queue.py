#!/usr/bin/env python3
"""Drain leased shock-relay offline deliveries.

Successful provider handoffs are committed. Failures are requeued after a
bounded delay, so every command is attempted at most once per drain run. The
queue has at-least-once semantics: a provider timeout may produce a duplicate
user-visible delivery after a later retry.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from offline_queue import QueueError, claim, complete, fail  # noqa: E402

SERVICE_SCRIPTS = {
    "telegram": PROJECT_ROOT / "services" / "telegram" / "send_message.py",
    "whatsapp": PROJECT_ROOT / "services" / "whatsapp" / "send_message.py",
    "twilio": PROJECT_ROOT / "services" / "twilio" / "send_sms.py",
    "gmail": PROJECT_ROOT / "services" / "gmail-imap" / "send_email.py",
    "signal": PROJECT_ROOT / "services" / "signal-cli" / "send_message.py",
}
DEFAULT_RETRY_SECONDS = 60


def _build_argv(service: str, payload: dict) -> list[str]:
    """Reconstruct provider CLI arguments from one durable payload."""

    if service == "telegram":
        argv = [payload["chat_id"], payload["message"]]
        if payload.get("config"):
            argv += ["--config", payload["config"]]
        if payload.get("parse_mode"):
            argv += ["--parse-mode", payload["parse_mode"]]
        return argv
    if service == "whatsapp":
        argv = [payload["recipient"], payload["message"]]
        if payload.get("config"):
            argv += ["--config", payload["config"]]
        return argv
    if service == "twilio":
        argv = [payload["to_number"], payload["message"]]
        if payload.get("config"):
            argv += ["--config", payload["config"]]
        return argv
    if service == "gmail":
        argv = [payload["to_address"], payload["subject"], payload["body"]]
        if payload.get("config"):
            argv += ["--config", payload["config"]]
        for cc in payload.get("cc", []):
            argv += ["--cc", cc]
        for bcc in payload.get("bcc", []):
            argv += ["--bcc", bcc]
        for header in payload.get("header", []):
            argv += ["--header", header]
        return argv
    if service == "signal":
        argv = [payload["recipient"], payload["message"]]
        if payload.get("config"):
            argv += ["--config", payload["config"]]
        for metadata in payload.get("meta", []):
            argv += ["--meta", metadata]
        return argv
    raise ValueError(f"unknown service: {service!r}")


def _retry_seconds() -> int:
    configured = os.environ.get("SHOCK_RELAY_QUEUE_RETRY_SECONDS", str(DEFAULT_RETRY_SECONDS))
    try:
        value = int(configured)
    except ValueError as exc:
        raise QueueError("SHOCK_RELAY_QUEUE_RETRY_SECONDS must be a non-negative integer") from exc
    if value < 0:
        raise QueueError("SHOCK_RELAY_QUEUE_RETRY_SECONDS must be a non-negative integer")
    return value


def drain(*, verbose: bool = False, max_items: int | None = None) -> int:
    """Lease and process due deliveries once, returning nonzero on failures."""

    worker_id = f"shock-relay-drain:{socket.gethostname()}:{os.getpid()}"
    retry_seconds = _retry_seconds()
    environment = {**os.environ, "SHOCK_RELAY_NO_QUEUE": "1"}
    processed = delivered = failed = rejected = 0

    while max_items is None or processed < max_items:
        delivery = claim(worker_id)
        if delivery is None:
            break
        processed += 1
        service = delivery["service"]
        script = SERVICE_SCRIPTS.get(service)
        description = f"{service} | id {delivery['operation_id'][:8]}"
        if script is None or not script.is_file():
            fail(
                delivery,
                worker_id=worker_id,
                problem={"code": "unknown-service", "service": service},
                retry_after_seconds=None,
            )
            rejected += 1
            print(f"  [REJECTED] {description}: unknown service", file=sys.stderr)
            continue
        try:
            argv = _build_argv(service, delivery["payload"])
        except (KeyError, TypeError, ValueError) as exc:
            fail(
                delivery,
                worker_id=worker_id,
                problem={"code": "invalid-payload", "detail": str(exc)},
                retry_after_seconds=None,
            )
            rejected += 1
            print(f"  [REJECTED] {description}: invalid payload", file=sys.stderr)
            continue
        if verbose:
            print(f"  Sending: {description}")
        try:
            result = subprocess.run([sys.executable, str(script), *argv], env=environment)
        except OSError as exc:
            fail(
                delivery,
                worker_id=worker_id,
                problem={"code": "process-error", "detail": str(exc)},
                retry_after_seconds=retry_seconds,
            )
            failed += 1
            continue
        if result.returncode == 0:
            complete(delivery, worker_id=worker_id, result={"service": service, "exit_code": 0})
            delivered += 1
        else:
            fail(
                delivery,
                worker_id=worker_id,
                problem={"code": "provider-exit", "exit_code": result.returncode},
                retry_after_seconds=retry_seconds,
            )
            failed += 1
    if verbose or processed:
        print(f"Delivered: {delivered}, requeued: {failed}, rejected: {rejected}")
    return 1 if failed or rejected else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true", help="show each claimed delivery")
    parser.add_argument(
        "--max-items", type=int, help="process no more than this many due deliveries"
    )
    arguments = parser.parse_args()
    if arguments.max_items is not None and arguments.max_items < 0:
        parser.error("--max-items must be non-negative")
    try:
        return drain(verbose=arguments.verbose, max_items=arguments.max_items)
    except QueueError as exc:
        print(f"queue error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
