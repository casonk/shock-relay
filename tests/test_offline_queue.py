"""Durable offline queue behavior and leased drain semantics."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
DIFFERENTIAL_SRC = REPO_ROOT.parent / "differential" / "src"
sys.path.insert(0, str(DIFFERENTIAL_SRC))
sys.path.insert(0, str(REPO_ROOT))

import offline_queue  # noqa: E402


def _load_drain_module():
    spec = importlib.util.spec_from_file_location(
        "shock_relay_drain_queue_test", REPO_ROOT / "scripts" / "drain_queue.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)

    def test_missing_differential_runtime_reports_a_setup_error(self) -> None:
        with patch.object(offline_queue, "import_module", side_effect=ImportError("missing")):
            with self.assertRaisesRegex(offline_queue.QueueError, "requires the reviewed"):
                offline_queue.queue_store(queue_dir=self.directory)

    def test_claim_complete_and_retry_are_lease_fenced(self) -> None:
        operation_id = offline_queue.enqueue(
            "telegram",
            {"chat_id": "123", "message": "offline"},
            queue_dir=self.directory,
            origin_node="air",
        )
        claimed = offline_queue.claim("worker", queue_dir=self.directory)
        assert claimed is not None
        self.assertEqual(claimed["operation_id"], operation_id)
        offline_queue.fail(
            claimed,
            worker_id="worker",
            problem={"code": "offline"},
            retry_after_seconds=0,
            queue_dir=self.directory,
        )
        retry = offline_queue.claim("worker", queue_dir=self.directory)
        assert retry is not None
        offline_queue.complete(
            retry,
            worker_id="worker",
            result={"service": "telegram", "exit_code": 0},
            queue_dir=self.directory,
        )
        self.assertIsNone(offline_queue.claim("worker", queue_dir=self.directory))

    def test_legacy_jsonl_import_is_idempotent_before_rename(self) -> None:
        legacy = self.directory / "queue.jsonl"
        legacy.write_text(
            json.dumps({"service": "telegram", "payload": {"chat_id": "123", "message": "legacy"}})
            + "\n",
            encoding="utf-8",
        )
        offline_queue.queue_store(queue_dir=self.directory, origin_node="air")
        delivery = offline_queue.claim("worker", queue_dir=self.directory)
        assert delivery is not None
        self.assertEqual(delivery["payload"]["message"], "legacy")
        self.assertFalse(legacy.exists())
        self.assertTrue((self.directory / "queue.jsonl.migrated").is_file())

    def test_drain_requeues_failed_provider_once_per_run(self) -> None:
        offline_queue.enqueue(
            "telegram",
            {"chat_id": "123", "message": "retry"},
            queue_dir=self.directory,
            origin_node="air",
        )
        drain_queue = _load_drain_module()
        with (
            patch.object(
                drain_queue,
                "claim",
                side_effect=lambda worker: offline_queue.claim(worker, queue_dir=self.directory),
            ),
            patch.object(
                drain_queue,
                "fail",
                side_effect=lambda delivery, **kwargs: offline_queue.fail(
                    delivery, queue_dir=self.directory, **kwargs
                ),
            ),
            patch.object(
                drain_queue,
                "complete",
                side_effect=lambda delivery, **kwargs: offline_queue.complete(
                    delivery, queue_dir=self.directory, **kwargs
                ),
            ),
            patch.object(
                drain_queue.subprocess,
                "run",
                return_value=type("Result", (), {"returncode": 1})(),
            ),
            patch.dict("os.environ", {"SHOCK_RELAY_QUEUE_RETRY_SECONDS": "60"}, clear=False),
        ):
            self.assertEqual(drain_queue.drain(), 1)
        self.assertIsNone(offline_queue.claim("worker", queue_dir=self.directory))
