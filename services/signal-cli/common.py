#!/usr/bin/env python3
from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


def extract_account_and_bus_name(config_path: str) -> tuple[str, str | None]:
    try:
        config_text = Path(config_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"ERROR: Cannot read config file: {config_path} ({exc})") from exc

    lines = config_text.splitlines()
    account = ""
    bus_name = None

    in_signal_cli = False
    base_indent = None

    def val_from_line(line: str) -> str:
        match = re.match(r"^\s*[^:]+:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s#]+))\s*(?:#.*)?$", line)
        if not match:
            return ""
        return next(value for value in match.groups() if value is not None)

    for line in lines:
        if not in_signal_cli:
            if re.match(r"^\s*signal_cli:\s*$", line):
                in_signal_cli = True
                base_indent = len(line) - len(line.lstrip())
            continue

        if line.strip() != "":
            indent = len(line) - len(line.lstrip())
            if base_indent is not None and indent <= base_indent:
                break

        if re.match(r"^\s*account:\s*", line):
            account = val_from_line(line)
        elif re.match(r"^\s*bus_name:\s*", line):
            bus_name = val_from_line(line) or None

    if not account:
        raise RuntimeError("ERROR: Missing signal_cli.account in config.local.yaml")

    return account, bus_name


def normalize_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in metadata.items():
        key = str(name or "").strip().lower()
        text = str(value or "").strip()
        if not key:
            raise ConfigError("ERROR: Signal metadata key cannot be empty")
        if not key.startswith("cc-"):
            raise ConfigError("ERROR: Signal metadata keys must start with 'cc-'")
        if ":" in key:
            raise ConfigError("ERROR: Signal metadata keys must not contain ':'")
        if any(ch in key for ch in "\r\n") or any(ch in text for ch in "\r\n"):
            raise ConfigError("ERROR: Signal metadata must not contain newlines")
        normalized[key] = text
    return normalized


def parse_metadata_args(values: Iterable[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw_value in values:
        text = str(raw_value or "")
        if ":" not in text:
            raise ConfigError("ERROR: --meta must use the form 'key: value'")
        key, value = text.split(":", 1)
        metadata.update(normalize_metadata({key: value}))
    return metadata


def build_message_with_metadata(message: str, metadata: dict[str, Any]) -> str:
    normalized = normalize_metadata(metadata)
    if not normalized:
        return message
    lines = [f"{key}: {value}" for key, value in normalized.items()]
    if message:
        return "\n".join([*lines, "", message])
    return "\n".join([*lines, ""])
