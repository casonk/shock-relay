#!/usr/bin/env python3
import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


class ConfigError(RuntimeError):
    pass


class GatewayError(RuntimeError):
    pass


@dataclass
class HttpResponse:
    status_code: int
    text: str
    json_body: Any


@dataclass
class TelegramConfig:
    config_path: str
    api_base_url: str
    bot_token: str
    timeout_seconds: int
    allowed_chat_ids: List[str]
    allowed_updates: List[str]
    default_parse_mode: str
    insecure_skip_verify: bool
    ca_cert_path: str


def default_config_path() -> str:
    return os.environ.get(
        "TELEGRAM_LOCAL_CONFIG",
        str(Path(__file__).resolve().parent / "config.local.yaml"),
    )


def load_config(config_path: str) -> TelegramConfig:
    try:
        config_text = Path(config_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"ERROR: Cannot read config file: {config_path} ({exc})"
        ) from exc

    config = parse_simple_yaml(config_text)
    telegram_cfg = as_mapping(config.get("telegram"), "telegram")
    tls_cfg = as_mapping(telegram_cfg.get("tls"), "telegram.tls", allow_empty=True)

    api_base_url = (
        optional_string(telegram_cfg.get("api_base_url")) or "https://api.telegram.org"
    )
    if not api_base_url.lower().startswith("https://"):
        raise ConfigError("ERROR: telegram.api_base_url must use https://")

    bot_token = optional_string(telegram_cfg.get("bot_token")) or resolve_env_value(
        optional_string(telegram_cfg.get("bot_token_env")),
        field_name="telegram.bot_token_env",
        required=False,
    )
    if not bot_token:
        raise ConfigError(
            "ERROR: Missing telegram.bot_token or telegram.bot_token_env in config.local.yaml"
        )

    timeout_seconds = parse_int(
        telegram_cfg.get("timeout_seconds"),
        default=30,
        field_name="telegram.timeout_seconds",
    )
    allowed_chat_ids = read_scalar_list(
        telegram_cfg.get("allowed_chat_ids"), "telegram.allowed_chat_ids"
    )
    allowed_updates = read_scalar_list(
        telegram_cfg.get("allowed_updates"), "telegram.allowed_updates"
    ) or ["message"]
    default_parse_mode = optional_string(telegram_cfg.get("default_parse_mode"))

    insecure_skip_verify = parse_bool(
        tls_cfg.get("insecure_skip_verify"),
        default=False,
        field_name="telegram.tls.insecure_skip_verify",
    )
    ca_cert_path = optional_string(tls_cfg.get("ca_cert_path")) or resolve_env_value(
        optional_string(tls_cfg.get("ca_cert_path_env")),
        field_name="telegram.tls.ca_cert_path_env",
        required=False,
    )
    if insecure_skip_verify and ca_cert_path:
        raise ConfigError(
            "ERROR: Configure either telegram.tls.insecure_skip_verify or a CA cert path, not both"
        )
    if ca_cert_path and not Path(ca_cert_path).is_file():
        raise ConfigError(f"ERROR: CA certificate file does not exist: {ca_cert_path}")

    return TelegramConfig(
        config_path=config_path,
        api_base_url=api_base_url.rstrip("/"),
        bot_token=bot_token,
        timeout_seconds=timeout_seconds,
        allowed_chat_ids=allowed_chat_ids,
        allowed_updates=allowed_updates,
        default_parse_mode=default_parse_mode,
        insecure_skip_verify=insecure_skip_verify,
        ca_cert_path=ca_cert_path,
    )


def send_message(
    config: TelegramConfig,
    chat_id: str,
    message: str,
    parse_mode: Optional[str] = None,
) -> HttpResponse:
    validate_chat_id(config, chat_id)
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": message,
    }
    parse_mode_to_use = parse_mode or config.default_parse_mode
    if parse_mode_to_use:
        payload["parse_mode"] = parse_mode_to_use
    return request_api(config, "sendMessage", payload=payload)


def get_updates(
    config: TelegramConfig,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    timeout: Optional[int] = None,
    allowed_updates: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if offset is not None:
        payload["offset"] = offset
    if limit is not None:
        payload["limit"] = limit
    if timeout is not None:
        payload["timeout"] = timeout

    effective_allowed_updates = allowed_updates or config.allowed_updates
    if effective_allowed_updates:
        payload["allowed_updates"] = effective_allowed_updates

    client_timeout = config.timeout_seconds
    if timeout is not None:
        client_timeout = max(client_timeout, timeout + 5)

    response = request_api(
        config, "getUpdates", payload=payload, timeout_seconds=client_timeout
    )
    return normalize_updates_response(get_result(response))


def get_me(config: TelegramConfig) -> Dict[str, Any]:
    response = request_api(
        config, "getMe", payload={}, timeout_seconds=config.timeout_seconds
    )
    result = get_result(response)
    if not isinstance(result, dict):
        raise GatewayError("Telegram getMe response did not contain an object result")
    return result


def request_api(
    config: TelegramConfig,
    method_name: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[int] = None,
) -> HttpResponse:
    response = request_json(
        method="POST",
        url=build_method_url(config, method_name),
        timeout_seconds=timeout_seconds or config.timeout_seconds,
        payload=payload or {},
        insecure_skip_verify=config.insecure_skip_verify,
        ca_cert_path=config.ca_cert_path,
    )

    body = response.json_body
    if not isinstance(body, dict):
        raise GatewayError("Telegram API response was not a JSON object")
    if body.get("ok") is not True:
        description = (
            optional_string(body.get("description")) or "Telegram API request failed"
        )
        error_code = optional_string(body.get("error_code"))
        if error_code:
            raise GatewayError(f"Telegram API error {error_code}: {description}")
        raise GatewayError(f"Telegram API error: {description}")
    return response


def get_result(response: HttpResponse) -> Any:
    body = response.json_body
    if not isinstance(body, dict):
        raise GatewayError("Telegram API response was not a JSON object")
    return body.get("result")


def normalize_updates_response(result: Any) -> Dict[str, Any]:
    if not isinstance(result, list):
        raise GatewayError("Telegram getUpdates result was not a list")

    normalized = [normalize_update(update) for update in result]
    update_ids = [
        update["update_id"]
        for update in normalized
        if isinstance(update.get("update_id"), int)
    ]
    next_offset = max(update_ids) + 1 if update_ids else None
    return {
        "updates": normalized,
        "next_offset": next_offset,
    }


def normalize_update(update: Any) -> Dict[str, Any]:
    if not isinstance(update, dict):
        raise GatewayError("Telegram update was not a JSON object")

    update_type = ""
    message_payload: Dict[str, Any] = {}
    for candidate in (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
    ):
        candidate_value = update.get(candidate)
        if isinstance(candidate_value, dict):
            update_type = candidate
            message_payload = candidate_value
            break

    chat_payload = (
        message_payload.get("chat")
        if isinstance(message_payload.get("chat"), dict)
        else {}
    )
    from_payload = (
        message_payload.get("from")
        if isinstance(message_payload.get("from"), dict)
        else {}
    )
    text = optional_string(message_payload.get("text")) or optional_string(
        message_payload.get("caption")
    )

    return {
        "update_id": update.get("update_id"),
        "type": update_type or None,
        "message_id": message_payload.get("message_id"),
        "chat_id": chat_payload.get("id"),
        "chat_type": chat_payload.get("type"),
        "chat_title": first_non_empty(
            chat_payload, ["title", "username", "first_name"]
        ),
        "from_id": from_payload.get("id"),
        "from_username": from_payload.get("username"),
        "from_first_name": from_payload.get("first_name"),
        "text": text,
        "date": message_payload.get("date"),
        "raw": update,
    }


def update_fingerprint(update: Dict[str, Any]) -> str:
    update_id = update.get("update_id")
    if isinstance(update_id, int):
        return f"update:{update_id}"
    raw = update.get("raw", update)
    return json.dumps(raw, sort_keys=True, default=str)


def validate_chat_id(config: TelegramConfig, chat_id: str) -> None:
    if not config.allowed_chat_ids:
        return

    if any(chat_matches(chat_id, allowed) for allowed in config.allowed_chat_ids):
        return

    raise ConfigError(
        f"ERROR: Chat ID is not allowed by telegram.allowed_chat_ids: {chat_id}"
    )


def chat_matches(actual: Any, expected: Any) -> bool:
    actual_text = canonical_chat_id(actual)
    expected_text = canonical_chat_id(expected)
    return bool(actual_text and expected_text and actual_text == expected_text)


def canonical_chat_id(value: Any) -> str:
    text = optional_string(value)
    if not text:
        return ""
    if text.startswith("@"):
        return text.lower()
    if re.fullmatch(r"-?\d+", text):
        return str(int(text))
    return text


def build_method_url(config: TelegramConfig, method_name: str) -> str:
    return f"{config.api_base_url}/bot{config.bot_token}/{method_name}"


def request_json(
    method: str,
    url: str,
    timeout_seconds: int,
    payload: Optional[Dict[str, Any]] = None,
    insecure_skip_verify: bool = False,
    ca_cert_path: str = "",
) -> HttpResponse:
    request_headers = {"Content-Type": "application/json"}
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url=url, data=data, headers=request_headers, method=method
    )
    ssl_context = build_ssl_context(
        insecure_skip_verify=insecure_skip_verify, ca_cert_path=ca_cert_path
    )

    try:
        with urllib.request.urlopen(
            request, timeout=timeout_seconds, context=ssl_context
        ) as response:
            text = response.read().decode(
                response.headers.get_content_charset() or "utf-8",
                errors="replace",
            )
            return HttpResponse(
                status_code=getattr(response, "status", 200),
                text=text,
                json_body=parse_json_body(text),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = f"HTTP {exc.code}: {body.strip() or exc.reason}"
        raise GatewayError(message) from exc
    except urllib.error.URLError as exc:
        raise GatewayError(f"Request failed: {exc.reason}") from exc


def build_ssl_context(
    insecure_skip_verify: bool, ca_cert_path: str
) -> Optional[ssl.SSLContext]:
    if insecure_skip_verify:
        return ssl._create_unverified_context()
    if ca_cert_path:
        return ssl.create_default_context(cafile=ca_cert_path)
    return None


def parse_json_body(text: str) -> Any:
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def first_non_empty(mapping: Dict[str, Any], keys: List[str]) -> Optional[str]:
    for key in keys:
        value = optional_string(mapping.get(key))
        if value:
            return value
    return None


def read_scalar_list(value: Any, field_name: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"ERROR: {field_name} must be a YAML list")

    result = []
    for item in value:
        item_str = optional_string(item)
        if not item_str:
            raise ConfigError(
                f"ERROR: {field_name} must contain only non-empty scalars"
            )
        result.append(item_str)
    return result


def optional_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def parse_int(value: Any, default: int, field_name: str) -> int:
    if value is None or value == "":
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"ERROR: {field_name} must be an integer") from exc


def parse_bool(value: Any, default: bool, field_name: str) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value

    lowered = str(value).strip().lower()
    if lowered in ("true", "yes", "1", "on"):
        return True
    if lowered in ("false", "no", "0", "off"):
        return False
    raise ConfigError(f"ERROR: {field_name} must be a boolean")


def resolve_env_value(
    env_name: Optional[str], field_name: str, required: bool = True
) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name, "")
    if value:
        return value
    if required:
        raise ConfigError(
            f"ERROR: Environment variable {env_name} referenced by {field_name} is not set"
        )
    return ""


def as_mapping(
    value: Any, field_name: str, allow_empty: bool = False
) -> Dict[str, Any]:
    if value is None:
        if allow_empty:
            return {}
        raise ConfigError(f"ERROR: Missing {field_name} in config.local.yaml")
    if not isinstance(value, dict):
        raise ConfigError(f"ERROR: {field_name} must be a YAML mapping")
    return value


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Any] = [(-1, root)]

    for index, raw_line in enumerate(lines):
        line = strip_comment(raw_line).rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.lstrip(" ")

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]

        if stripped.startswith("- "):
            if not isinstance(parent, list):
                raise ConfigError(
                    f"ERROR: Unexpected YAML list item near line {index + 1}"
                )
            parent.append(parse_scalar(stripped[2:].strip()))
            continue

        if ":" not in stripped:
            raise ConfigError(f"ERROR: Invalid YAML syntax near line {index + 1}")
        if not isinstance(parent, dict):
            raise ConfigError(f"ERROR: Unexpected YAML mapping near line {index + 1}")

        key, value_text = stripped.split(":", 1)
        key = key.strip()
        value_text = value_text.strip()

        if not value_text:
            container_kind = next_container_kind(lines, index, indent)
            if container_kind is list:
                container: Any = []
            elif container_kind is dict:
                container = {}
            else:
                parent[key] = None
                continue
            parent[key] = container
            stack.append((indent, container))
            continue

        parent[key] = parse_scalar(value_text)

    return root


def next_container_kind(
    lines: List[str], start_index: int, current_indent: int
) -> Optional[type]:
    for raw_line in lines[start_index + 1 :]:
        line = strip_comment(raw_line).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= current_indent:
            return None
        return list if line.lstrip(" ").startswith("- ") else dict
    return None


def strip_comment(raw_line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(raw_line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return raw_line[:index]
    return raw_line


def parse_scalar(value_text: str) -> Any:
    lowered = value_text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "~"):
        return None
    if value_text in ("[]", "[ ]"):
        return []
    if value_text in ("{}", "{ }"):
        return {}
    if re.fullmatch(r"-?\d+", value_text):
        return int(value_text)
    if (
        len(value_text) >= 2
        and value_text[0] == value_text[-1]
        and value_text[0] in ("'", '"')
    ):
        if value_text[0] == "'":
            return value_text[1:-1].replace("''", "'")
        return bytes(value_text[1:-1], "utf-8").decode("unicode_escape")
    return value_text
