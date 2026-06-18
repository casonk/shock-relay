from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from dyno_lab.module import load_module_by_path

REPO_ROOT = Path(__file__).resolve().parents[1]
GMAIL_DIR = REPO_ROOT / "services/gmail-imap"
if str(GMAIL_DIR) not in sys.path:
    sys.path.insert(0, str(GMAIL_DIR))


def _load(name: str, path: Path):
    return load_module_by_path(path, module_name=name)


def test_digest_queue_appends_and_pops_entries(tmp_path):
    digest_queue = _load(
        "shock_relay_gmail_digest_queue_test",
        REPO_ROOT / "services/gmail-imap/digest_queue.py",
    )
    queue_file = tmp_path / "digest.jsonl"

    entry = digest_queue.enqueue_digest(
        to_addresses=["me@example.com"],
        subject="Receipt processed",
        body="Merchant: kroger",
        config_path="/tmp/config.local.yaml",
        service="intake",
        kind="receipt-processed",
        headers={"X-Portfolio-Service": "intake"},
        queue_file=queue_file,
    )

    loaded = digest_queue.load_entries(queue_file=queue_file)
    assert len(loaded) == 1
    assert loaded[0]["id"] == entry["id"]
    assert loaded[0]["to"] == ["me@example.com"]
    assert loaded[0]["headers"] == {"X-Portfolio-Service": "intake"}

    popped = digest_queue.pop_entries(queue_file=queue_file)
    assert [item["id"] for item in popped] == [entry["id"]]
    assert digest_queue.load_entries(queue_file=queue_file) == []


def test_send_digest_groups_by_config_and_recipient(tmp_path):
    digest_queue = _load(
        "shock_relay_gmail_digest_queue_send_test",
        REPO_ROOT / "services/gmail-imap/digest_queue.py",
    )
    send_digest = _load(
        "shock_relay_gmail_send_digest_test",
        REPO_ROOT / "services/gmail-imap/send_digest.py",
    )
    queue_file = tmp_path / "digest.jsonl"
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text("imap:\n  username: me@example.com\n", encoding="utf-8")
    sent = []

    for subject in ("Receipt processed: kroger $4.33", "CI fixed: casonk/example"):
        digest_queue.enqueue_digest(
            to_addresses=["me@example.com"],
            subject=subject,
            body="body",
            config_path=str(config_path),
            service="intake" if "Receipt" in subject else "traction-control",
            kind="test",
            queue_file=queue_file,
        )

    def fake_send_email(config, to_addresses, subject, body, headers):
        sent.append(
            {
                "config": config,
                "to": to_addresses,
                "subject": subject,
                "body": body,
                "headers": headers,
            }
        )
        return {"message_id": "<digest@example.com>"}

    with (
        patch.object(send_digest, "load_config", return_value={"config": "loaded"}),
        patch.object(send_digest, "send_email", fake_send_email),
    ):
        result = send_digest.send_queued_digest(
            default_config=str(config_path),
            queue_file=queue_file,
            subject_prefix="[portfolio] Digest",
        )

    assert result == {"queued": 2, "sent_digests": 1, "requeued": 0, "errors": []}
    assert len(sent) == 1
    assert sent[0]["to"] == ["me@example.com"]
    assert "2 notifications" in sent[0]["subject"]
    assert "intake: 1" in sent[0]["subject"]
    assert "traction-control: 1" in sent[0]["subject"]
    assert "Receipt processed: kroger $4.33" in sent[0]["body"]
    assert "CI fixed: casonk/example" in sent[0]["body"]
    assert sent[0]["headers"]["X-Crew-Chief-Intent"] == "digest"
    assert digest_queue.load_entries(queue_file=queue_file) == []


def test_send_digest_requeues_group_when_send_fails(tmp_path):
    digest_queue = _load(
        "shock_relay_gmail_digest_queue_requeue_test",
        REPO_ROOT / "services/gmail-imap/digest_queue.py",
    )
    send_digest = _load(
        "shock_relay_gmail_send_digest_requeue_test",
        REPO_ROOT / "services/gmail-imap/send_digest.py",
    )
    queue_file = tmp_path / "digest.jsonl"
    digest_queue.enqueue_digest(
        to_addresses=["me@example.com"],
        subject="Receipt processed",
        body="body",
        config_path="/tmp/config.local.yaml",
        service="intake",
        kind="test",
        queue_file=queue_file,
    )

    with (
        patch.object(send_digest, "load_config", return_value={"config": "loaded"}),
        patch.object(send_digest, "send_email", side_effect=RuntimeError("smtp down")),
    ):
        result = send_digest.send_queued_digest(
            default_config="/tmp/config.local.yaml",
            queue_file=queue_file,
        )

    assert result["queued"] == 1
    assert result["sent_digests"] == 0
    assert result["requeued"] == 1
    assert "smtp down" in result["errors"][0]
    assert len(digest_queue.load_entries(queue_file=queue_file)) == 1
