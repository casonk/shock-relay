from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

SERVICE_DIR = Path(__file__).resolve().parents[1] / "services" / "signal-cli"


def _load_module(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SERVICE_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SERVICE_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


signal_common = _load_module("signal_cli_common", "common.py")
signal_send_message = _load_module("signal_cli_send_message", "send_message.py")


def test_parse_metadata_args_accepts_cc_protocol_keys():
    metadata = signal_common.parse_metadata_args(
        ["cc-service: intake", "cc-intent: request", "cc-target: crew-chief"]
    )
    assert metadata == {
        "cc-service": "intake",
        "cc-intent": "request",
        "cc-target": "crew-chief",
    }


def test_parse_metadata_args_rejects_missing_colon():
    try:
        signal_common.parse_metadata_args(["cc-service intake"])
    except signal_common.ConfigError as exc:
        assert "--meta must use the form" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_build_message_with_metadata_prepends_block():
    message = signal_common.build_message_with_metadata(
        "hello from automation",
        {"cc-service": "crew-chief", "cc-intent": "response"},
    )
    assert message == (
        "cc-service: crew-chief\ncc-intent: response\n\nhello from automation"
    )


def test_send_message_main_includes_metadata_block(monkeypatch, tmp_path):
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text("signal_cli:\n  account: +15551234567\n", encoding="utf-8")

    seen = {}

    def fake_run(cmd, check):
        seen["cmd"] = cmd
        seen["check"] = check
        return Mock(returncode=0)

    monkeypatch.setattr(signal_send_message.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "send_message.py",
            "--config",
            str(config_path),
            "--meta",
            "cc-service: intake",
            "--meta",
            "cc-intent: request",
            "+15550000000",
            "status",
        ],
    )

    assert signal_send_message.main() == 0
    assert seen["check"] is True
    assert seen["cmd"][:5] == ["signal-cli", "-a", "+15551234567", "send", "-m"]
    assert seen["cmd"][5] == "cc-service: intake\ncc-intent: request\n\nstatus"
    assert seen["cmd"][6] == "+15550000000"
