#!/usr/bin/env python3
import base64
from dataclasses import dataclass
import json
import os
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


class NetworkError(GatewayError):
    """Raised when a send fails due to network connectivity, not an API error."""

    pass


@dataclass
class HttpResponse:
    status_code: int
    text: str
    json_body: Any


@dataclass
class WhatsAppConfig:
    config_path: str
    base_url: str
    send_path: str
    receive_path: str
    timeout_seconds: int
    sender: str
    allowed_recipients: List[str]
    headers: Dict[str, str]
    insecure_skip_verify: bool
    ca_cert_path: str


def default_config_path() -> str:
    return os.environ.get(
        "WHATSAPP_LOCAL_CONFIG",
        str(Path(__file__).resolve().parent / "config.local.yaml"),
    )


def load_config(config_path: str) -> WhatsAppConfig:
    try:
        config_text = Path(config_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"ERROR: Cannot read config file: {config_path} ({exc})") from exc

    config = parse_simple_yaml(config_text)
    http_cfg = as_mapping(config.get("http"), "http")
    messaging_cfg = as_mapping(config.get("messaging"), "messaging", allow_empty=True)
    auth_cfg = as_mapping(http_cfg.get("auth"), "http.auth", allow_empty=True)
    tls_cfg = as_mapping(http_cfg.get("tls"), "http.tls", allow_empty=True)

    base_url = require_string(http_cfg.get("base_url"), "http.base_url")
    if not base_url.lower().startswith("https://"):
        raise ConfigError("ERROR: http.base_url must use https://")
    send_path = optional_string(http_cfg.get("send_path")) or "/messages"
    receive_path = optional_string(http_cfg.get("receive_path")) or "/messages/inbound"
    timeout_seconds = parse_int(
        http_cfg.get("timeout_seconds"), default=30, field_name="http.timeout_seconds"
    )
    insecure_skip_verify = parse_bool(
        tls_cfg.get("insecure_skip_verify"),
        default=False,
        field_name="http.tls.insecure_skip_verify",
    )
    ca_cert_path = optional_string(tls_cfg.get("ca_cert_path")) or resolve_env_value(
        optional_string(tls_cfg.get("ca_cert_path_env")),
        field_name="http.tls.ca_cert_path_env",
        required=False,
    )
    if insecure_skip_verify and ca_cert_path:
        raise ConfigError(
            "ERROR: Configure either http.tls.insecure_skip_verify or a CA cert path, not both"
        )
    if ca_cert_path and not Path(ca_cert_path).is_file():
        raise ConfigError(f"ERROR: CA certificate file does not exist: {ca_cert_path}")

    sender = optional_string(messaging_cfg.get("from")) or resolve_env_value(
        optional_string(messaging_cfg.get("from_env")),
        field_name="messaging.from_env",
        required=False,
    )

    if not sender:
        raise ConfigError(
            "ERROR: Missing messaging.from or messaging.from_env in config.local.yaml"
        )

    allowed_recipients = read_allowed_recipients(messaging_cfg)
    headers = build_auth_headers(http_cfg, auth_cfg)

    return WhatsAppConfig(
        config_path=config_path,
        base_url=base_url.rstrip("/"),
        send_path=send_path,
        receive_path=receive_path,
        timeout_seconds=timeout_seconds,
        sender=sender,
        allowed_recipients=allowed_recipients,
        headers=headers,
        insecure_skip_verify=insecure_skip_verify,
        ca_cert_path=ca_cert_path,
    )


def send_message(
    config: WhatsAppConfig,
    recipient: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> HttpResponse:
    validate_recipient(config, recipient)

    payload: Dict[str, Any] = {
        "from": config.sender,
        "to": recipient,
        "recipient": recipient,
        "message": message,
        "text": message,
        "type": "text",
    }
    if metadata:
        payload["metadata"] = metadata

    return request_json(
        method="POST",
        url=build_url(config.base_url, config.send_path),
        timeout_seconds=config.timeout_seconds,
        headers=config.headers,
        payload=payload,
        insecure_skip_verify=config.insecure_skip_verify,
        ca_cert_path=config.ca_cert_path,
    )


def receive_messages(
    config: WhatsAppConfig,
    limit: Optional[int] = None,
    timeout: Optional[int] = None,
    cursor: Optional[str] = None,
    since: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, str] = {}
    if limit is not None:
        params["limit"] = str(limit)
    if timeout is not None:
        params["timeout"] = str(timeout)
    if cursor:
        params["cursor"] = cursor
    if since:
        params["since"] = since
    if config.sender:
        params["to"] = config.sender

    response = request_json(
        method="GET",
        url=build_url(config.base_url, config.receive_path, params=params),
        timeout_seconds=timeout if timeout is not None else config.timeout_seconds,
        headers=config.headers,
        insecure_skip_verify=config.insecure_skip_verify,
        ca_cert_path=config.ca_cert_path,
    )
    return normalize_receive_response(response.json_body)


def normalize_receive_response(payload: Any) -> Dict[str, Any]:
    next_cursor = None

    if isinstance(payload, list):
        raw_messages = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("messages"), list):
            raw_messages = payload["messages"]
        elif isinstance(payload.get("items"), list):
            raw_messages = payload["items"]
        elif looks_like_message(payload):
            raw_messages = [payload]
        else:
            raise GatewayError("Receive response did not contain a messages list")

        next_cursor = first_non_empty(payload, ["next_cursor", "cursor", "next"])
    else:
        raise GatewayError("Receive response must be a JSON object or array")

    return {
        "messages": [normalize_message(item) for item in raw_messages],
        "next_cursor": next_cursor,
    }


def normalize_message(message: Any) -> Dict[str, Any]:
    if not isinstance(message, dict):
        return {
            "id": None,
            "from": None,
            "to": None,
            "text": str(message),
            "timestamp": None,
            "raw": message,
        }

    nested_message = message.get("message")
    nested_text = ""
    if isinstance(nested_message, dict):
        nested_text = first_non_empty(nested_message, ["text", "body", "message", "content"]) or ""

    return {
        "id": first_non_empty(message, ["id", "message_id", "sid", "wamid", "uuid"]),
        "from": first_non_empty(message, ["from", "sender", "source", "author"]),
        "to": first_non_empty(message, ["to", "recipient", "destination"]),
        "text": first_non_empty(message, ["text", "message", "body", "content"]) or nested_text,
        "timestamp": first_non_empty(
            message, ["timestamp", "created_at", "received_at", "date", "time"]
        ),
        "raw": message,
    }


def message_fingerprint(message: Dict[str, Any]) -> str:
    message_id = optional_string(message.get("id"))
    if message_id:
        return f"id:{message_id}"

    raw = message.get("raw", message)
    return json.dumps(raw, sort_keys=True, default=str)


def party_matches(actual: Optional[str], expected: Optional[str]) -> bool:
    if not actual or not expected:
        return False
    return canonical_party(actual) == canonical_party(expected)


def build_url(base_url: str, path: str, params: Optional[Dict[str, str]] = None) -> str:
    normalized_path = "/" + path.lstrip("/")
    url = urllib.parse.urljoin(base_url + "/", normalized_path.lstrip("/"))
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def request_json(
    method: str,
    url: str,
    timeout_seconds: int,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    insecure_skip_verify: bool = False,
    ca_cert_path: str = "",
) -> HttpResponse:
    request_headers = dict(headers or {})
    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(url=url, data=data, headers=request_headers, method=method)
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
        raise NetworkError(f"Request failed: {exc.reason}") from exc


def build_ssl_context(insecure_skip_verify: bool, ca_cert_path: str) -> Optional[ssl.SSLContext]:
    if insecure_skip_verify:
        return ssl._create_unverified_context()
    if ca_cert_path:
        return ssl.create_default_context(cafile=ca_cert_path)
    return None


def build_auth_headers(http_cfg: Dict[str, Any], auth_cfg: Dict[str, Any]) -> Dict[str, str]:
    headers: Dict[str, str] = {}

    api_key_env = optional_string(http_cfg.get("api_key_env"))
    if api_key_env:
        header_name = optional_string(http_cfg.get("api_key_header")) or "X-API-Key"
        headers[header_name] = resolve_env_value(api_key_env, field_name="http.api_key_env")

    bearer_token_env = optional_string(auth_cfg.get("bearer_token_env"))
    basic_username_env = optional_string(auth_cfg.get("basic_username_env"))
    basic_password_env = optional_string(auth_cfg.get("basic_password_env"))
    if bearer_token_env and (basic_username_env or basic_password_env):
        raise ConfigError("ERROR: Configure either bearer auth or basic auth, not both")

    if bearer_token_env:
        token = resolve_env_value(bearer_token_env, field_name="http.auth.bearer_token_env")
        headers["Authorization"] = f"Bearer {token}"

    if basic_username_env or basic_password_env:
        if not basic_username_env or not basic_password_env:
            raise ConfigError(
                "ERROR: http.auth.basic_username_env and http.auth.basic_password_env must be set together"
            )
        username = resolve_env_value(basic_username_env, field_name="http.auth.basic_username_env")
        password = resolve_env_value(basic_password_env, field_name="http.auth.basic_password_env")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    return headers


def validate_recipient(config: WhatsAppConfig, recipient: str) -> None:
    if not config.allowed_recipients:
        return

    if any(party_matches(recipient, allowed) for allowed in config.allowed_recipients):
        return

    raise ConfigError(
        f"ERROR: Recipient is not allowed by messaging.allowed_recipients: {recipient}"
    )


def read_allowed_recipients(messaging_cfg: Dict[str, Any]) -> List[str]:
    recipients: List[str] = []
    recipients.extend(
        read_string_list(messaging_cfg.get("allowed_recipients"), "messaging.allowed_recipients")
    )

    env_names = read_string_list(
        messaging_cfg.get("allowed_recipient_envs"),
        "messaging.allowed_recipient_envs",
    )
    for env_name in env_names:
        raw_value = resolve_env_value(
            env_name, field_name=f"messaging.allowed_recipient_envs[{env_name}]"
        )
        recipients.extend(split_recipient_values(raw_value))

    normalized: List[str] = []
    seen = set()
    for item in recipients:
        candidate = item.strip()
        if not candidate:
            continue
        key = canonical_party(candidate)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized


def split_recipient_values(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"[\n,]+", value) if item.strip()]


def resolve_env_value(env_name: Optional[str], field_name: str, required: bool = True) -> str:
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


def canonical_party(value: str) -> str:
    normalized = value.strip().lower()
    for prefix in ("whatsapp:", "tel:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]

    if re.fullmatch(r"[+()\-\s0-9]+", normalized):
        normalized = re.sub(r"[^0-9+]", "", normalized)
    else:
        normalized = re.sub(r"\s+", "", normalized)
    return normalized


def looks_like_message(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(key in value for key in ("from", "to", "text", "message", "body", "content"))


def read_string_list(value: Any, field_name: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"ERROR: {field_name} must be a YAML list")

    result = []
    for item in value:
        item_str = optional_string(item)
        if not item_str:
            raise ConfigError(f"ERROR: {field_name} must contain only non-empty strings")
        result.append(item_str)
    return result


def require_string(value: Any, field_name: str) -> str:
    result = optional_string(value)
    if not result:
        raise ConfigError(f"ERROR: Missing {field_name} in config.local.yaml")
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


def as_mapping(value: Any, field_name: str, allow_empty: bool = False) -> Dict[str, Any]:
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
                raise ConfigError(f"ERROR: Unexpected YAML list item near line {index + 1}")
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
                container = []
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


def next_container_kind(lines: List[str], start_index: int, current_indent: int) -> Optional[type]:
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
    if len(value_text) >= 2 and value_text[0] == value_text[-1] and value_text[0] in ("'", '"'):
        if value_text[0] == "'":
            return value_text[1:-1].replace("''", "'")
        return bytes(value_text[1:-1], "utf-8").decode("unicode_escape")
    return value_text
