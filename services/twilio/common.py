#!/usr/bin/env python3
import base64
import configparser
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


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
class TwilioConfig:
    config_path: str
    api_base_url: str
    account_sid: str
    auth_token: str
    from_phone: str
    timeout_seconds: int
    allowed_recipients: list[str]
    insecure_skip_verify: bool
    ca_cert_path: str


ENTRY_NOT_FOUND_MARKERS = (
    "not found",
    "no entry",
    "could not find",
)
DEFAULT_KEEPASS_PROFILE = "infra"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUTO_PASS_CONFIG_PATH = _REPO_ROOT / "config" / "auto-pass.ini"


def default_config_path() -> str:
    return os.environ.get(
        "TWILIO_LOCAL_CONFIG",
        str(Path(__file__).resolve().parent / "config.local.yaml"),
    )


def _load_repo_auto_pass_config() -> dict[str, str]:
    if not _AUTO_PASS_CONFIG_PATH.is_file():
        return {}

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        with _AUTO_PASS_CONFIG_PATH.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        raise ConfigError(
            f"ERROR: Cannot read auto-pass config file: {_AUTO_PASS_CONFIG_PATH} ({exc})"
        ) from exc

    defaults: dict[str, str] = {}
    if parser.has_section("auto_pass"):
        profile = parser.get("auto_pass", "profile", fallback="").strip()
        if profile:
            defaults["profile"] = profile
    if parser.has_section("twilio"):
        for key, value in parser.items("twilio"):
            text = value.strip()
            if text:
                defaults[key] = text
    return defaults


def _candidate_keepass_entries(entry: str) -> tuple[str, ...]:
    normalized = entry.strip()
    if not normalized:
        return ()
    candidates = [normalized]
    if normalized.startswith("Twilio/"):
        candidates.append(f"twilio/{normalized.split('/', 1)[1]}")
    return tuple(dict.fromkeys(candidates))


def _resolve_keepass_value(
    entry: str,
    field: str,
    profile: str = DEFAULT_KEEPASS_PROFILE,
) -> str:
    """Resolve a single field from a KeePassXC entry via the auto-pass sibling repo."""
    if not entry:
        return ""
    import sys as _sys

    _ap_root = Path(__file__).resolve().parent.parent.parent.parent / "auto-pass"
    _src = str(_ap_root / "src")
    if _src not in _sys.path:
        _sys.path.insert(0, _src)
    from auto_pass.envfile import load_config_environment  # noqa: PLC0415
    from auto_pass.keepassxc import (
        KeepassCommandError,  # noqa: PLC0415
        resolve_keepassxc_entry,  # noqa: PLC0415
    )

    _ap_env = _ap_root / "config" / "auto-pass.env.local"
    if _ap_env.is_file():
        load_config_environment(_ap_env, profile=profile or None)
    last_error: KeepassCommandError | None = None
    for candidate in _candidate_keepass_entries(entry):
        try:
            result = resolve_keepassxc_entry(candidate, attrs_map={"value": field})
        except KeepassCommandError as exc:
            last_error = exc
            lowered = str(exc).lower()
            if any(marker in lowered for marker in ENTRY_NOT_FOUND_MARKERS):
                continue
            raise
        return result.get("value", "")
    if last_error is not None:
        raise last_error
    return ""


def load_config(config_path: str) -> TwilioConfig:
    try:
        config_text = Path(config_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"ERROR: Cannot read config file: {config_path} ({exc})") from exc

    config = parse_simple_yaml(config_text)
    repo_auto_pass = _load_repo_auto_pass_config()
    keepass_profile = (
        optional_string(config.get("keepass_profile"))
        or repo_auto_pass.get("profile")
        or DEFAULT_KEEPASS_PROFILE
    )
    twilio_cfg = as_mapping(config.get("twilio"), "twilio")
    sms_cfg = as_mapping(twilio_cfg.get("sms"), "twilio.sms", allow_empty=True)
    tls_cfg = as_mapping(twilio_cfg.get("tls"), "twilio.tls", allow_empty=True)
    account_sid_keepass_entry = optional_string(
        twilio_cfg.get("account_sid_keepass_entry")
    ) or repo_auto_pass.get("account_sid_keepass_entry", "")
    auth_token_keepass_entry = optional_string(
        twilio_cfg.get("auth_token_keepass_entry")
    ) or repo_auto_pass.get("auth_token_keepass_entry", "")
    from_phone_keepass_entry = optional_string(
        twilio_cfg.get("from_phone_keepass_entry")
    ) or repo_auto_pass.get("from_phone_keepass_entry", "")

    api_base_url = optional_string(twilio_cfg.get("api_base_url")) or "https://api.twilio.com"
    if not api_base_url.lower().startswith("https://"):
        raise ConfigError("ERROR: twilio.api_base_url must use https://")

    account_sid = (
        optional_string(twilio_cfg.get("account_sid"))
        or resolve_env_value(
            optional_string(twilio_cfg.get("account_sid_env")),
            field_name="twilio.account_sid_env",
            required=False,
        )
        or _resolve_keepass_value(
            account_sid_keepass_entry,
            "username",
            keepass_profile,
        )
    )
    auth_token = (
        optional_string(twilio_cfg.get("auth_token"))
        or resolve_env_value(
            optional_string(twilio_cfg.get("auth_token_env")),
            field_name="twilio.auth_token_env",
            required=False,
        )
        or _resolve_keepass_value(
            auth_token_keepass_entry,
            "password",
            keepass_profile,
        )
    )
    from_phone = (
        optional_string(twilio_cfg.get("from_phone"))
        or resolve_env_value(
            optional_string(twilio_cfg.get("from_phone_env")),
            field_name="twilio.from_phone_env",
            required=False,
        )
        or _resolve_keepass_value(
            from_phone_keepass_entry,
            "username",
            keepass_profile,
        )
    )

    if not account_sid:
        raise ConfigError(
            "ERROR: Missing twilio.account_sid, twilio.account_sid_env, or twilio.account_sid_keepass_entry in config.local.yaml"
        )
    if not auth_token:
        raise ConfigError(
            "ERROR: Missing twilio.auth_token, twilio.auth_token_env, or twilio.auth_token_keepass_entry in config.local.yaml"
        )
    if not from_phone:
        raise ConfigError(
            "ERROR: Missing twilio.from_phone, twilio.from_phone_env, or twilio.from_phone_keepass_entry in config.local.yaml"
        )

    timeout_seconds = parse_int(
        twilio_cfg.get("timeout_seconds"),
        default=30,
        field_name="twilio.timeout_seconds",
    )
    sms_enabled = parse_bool(sms_cfg.get("enabled"), default=True, field_name="twilio.sms.enabled")
    if not sms_enabled:
        raise ConfigError("ERROR: twilio.sms.enabled must be true to use the SMS scripts")

    allowed_recipients = read_allowed_recipients(sms_cfg)

    insecure_skip_verify = parse_bool(
        tls_cfg.get("insecure_skip_verify"),
        default=False,
        field_name="twilio.tls.insecure_skip_verify",
    )
    ca_cert_path = optional_string(tls_cfg.get("ca_cert_path")) or resolve_env_value(
        optional_string(tls_cfg.get("ca_cert_path_env")),
        field_name="twilio.tls.ca_cert_path_env",
        required=False,
    )
    if insecure_skip_verify and ca_cert_path:
        raise ConfigError(
            "ERROR: Configure either twilio.tls.insecure_skip_verify or a CA cert path, not both"
        )
    if ca_cert_path and not Path(ca_cert_path).is_file():
        raise ConfigError(f"ERROR: CA certificate file does not exist: {ca_cert_path}")

    return TwilioConfig(
        config_path=config_path,
        api_base_url=api_base_url.rstrip("/"),
        account_sid=account_sid,
        auth_token=auth_token,
        from_phone=from_phone,
        timeout_seconds=timeout_seconds,
        allowed_recipients=allowed_recipients,
        insecure_skip_verify=insecure_skip_verify,
        ca_cert_path=ca_cert_path,
    )


def send_sms(config: TwilioConfig, to_number: str, message: str) -> HttpResponse:
    validate_recipient(config, to_number)
    payload = {
        "From": config.from_phone,
        "To": to_number,
        "Body": message,
    }
    return request_twilio(config, method="POST", params=payload)


def list_messages(
    config: TwilioConfig,
    to_number: str | None = None,
    from_number: str | None = None,
    limit: int | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if to_number:
        params["To"] = to_number
    if from_number:
        params["From"] = from_number
    if page_size is not None:
        params["PageSize"] = page_size

    response = request_twilio(config, method="GET", params=params or None)
    return normalize_messages_response(get_messages_list(response), limit=limit)


def get_messages_list(response: HttpResponse) -> list[Any]:
    body = response.json_body
    if not isinstance(body, dict):
        raise GatewayError("Twilio API response was not a JSON object")
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise GatewayError("Twilio API response did not contain a messages list")
    return messages


def normalize_messages_response(messages: list[Any], limit: int | None = None) -> dict[str, Any]:
    normalized = [normalize_message(item) for item in messages]
    if limit is not None:
        normalized = normalized[:limit]
    return {
        "messages": normalized,
    }


def normalize_message(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise GatewayError("Twilio message was not a JSON object")

    return {
        "sid": optional_string(message.get("sid")),
        "direction": optional_string(message.get("direction")),
        "from": optional_string(message.get("from")),
        "to": optional_string(message.get("to")),
        "body": optional_string(message.get("body")),
        "status": optional_string(message.get("status")),
        "date_created": optional_string(message.get("date_created")),
        "date_sent": optional_string(message.get("date_sent")),
        "timestamp": extract_timestamp(message),
        "raw": message,
    }


def extract_timestamp(message: dict[str, Any]) -> int | None:
    for key in ("date_sent", "date_created", "date_updated"):
        value = optional_string(message.get(key))
        if not value:
            continue
        try:
            return int(parsedate_to_datetime(value).timestamp())
        except Exception:
            continue
    return None


def message_fingerprint(message: dict[str, Any]) -> str:
    sid = optional_string(message.get("sid"))
    if sid:
        return f"sid:{sid}"
    raw = message.get("raw", message)
    return json.dumps(raw, sort_keys=True, default=str)


def request_twilio(
    config: TwilioConfig,
    method: str,
    params: dict[str, Any] | None = None,
) -> HttpResponse:
    return request_form(
        method=method,
        url=build_messages_url(config),
        username=config.account_sid,
        password=config.auth_token,
        timeout_seconds=config.timeout_seconds,
        params=params or {},
        insecure_skip_verify=config.insecure_skip_verify,
        ca_cert_path=config.ca_cert_path,
    )


def build_messages_url(config: TwilioConfig) -> str:
    return f"{config.api_base_url}/2010-04-01/Accounts/{config.account_sid}/Messages.json"


def request_form(
    method: str,
    url: str,
    username: str,
    password: str,
    timeout_seconds: int,
    params: dict[str, Any],
    insecure_skip_verify: bool = False,
    ca_cert_path: str = "",
) -> HttpResponse:
    encoded_params = urllib.parse.urlencode(
        {key: value for key, value in params.items() if value is not None}
    )
    request_url = url
    data = None

    if method == "GET":
        if encoded_params:
            request_url = f"{url}?{encoded_params}"
    else:
        data = encoded_params.encode("utf-8")

    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    headers = {
        "Authorization": f"Basic {token}",
    }
    if method != "GET":
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(url=request_url, data=data, headers=headers, method=method)
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


def build_ssl_context(insecure_skip_verify: bool, ca_cert_path: str) -> ssl.SSLContext | None:
    if insecure_skip_verify:
        raise ConfigError(
            "insecure_skip_verify=true is not supported. "
            "For private or self-signed gateways, set tls.ca_cert_path to your CA certificate instead."
        )
    if ca_cert_path:
        return ssl.create_default_context(cafile=ca_cert_path)
    return None


def validate_recipient(config: TwilioConfig, recipient: str) -> None:
    if not config.allowed_recipients:
        return
    if any(phone_matches(recipient, allowed) for allowed in config.allowed_recipients):
        return
    raise ConfigError(
        f"ERROR: Recipient is not allowed by twilio.sms.allowed_recipients: {recipient}"
    )


def read_allowed_recipients(sms_cfg: dict[str, Any]) -> list[str]:
    recipients = read_scalar_list(
        sms_cfg.get("allowed_recipients"), "twilio.sms.allowed_recipients"
    )
    env_names = read_scalar_list(
        sms_cfg.get("allowed_recipient_envs"), "twilio.sms.allowed_recipient_envs"
    )

    for env_name in env_names:
        raw_value = resolve_env_value(
            env_name, field_name=f"twilio.sms.allowed_recipient_envs[{env_name}]"
        )
        recipients.extend(split_values(raw_value))

    normalized: list[str] = []
    seen = set()
    for item in recipients:
        candidate = item.strip()
        if not candidate:
            continue
        key = canonical_phone(candidate)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized


def phone_matches(actual: Any, expected: Any) -> bool:
    actual_text = canonical_phone(actual)
    expected_text = canonical_phone(expected)
    return bool(actual_text and expected_text and actual_text == expected_text)


def canonical_phone(value: Any) -> str:
    text = optional_string(value)
    if not text:
        return ""
    return re.sub(r"[^0-9+]", "", text)


def split_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,]+", value) if item.strip()]


def parse_json_body(text: str) -> Any:
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def read_scalar_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"ERROR: {field_name} must be a YAML list")

    result = []
    for item in value:
        item_str = optional_string(item)
        if not item_str:
            raise ConfigError(f"ERROR: {field_name} must contain only non-empty scalars")
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


def resolve_env_value(env_name: str | None, field_name: str, required: bool = True) -> str:
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


def as_mapping(value: Any, field_name: str, allow_empty: bool = False) -> dict[str, Any]:
    if value is None:
        if allow_empty:
            return {}
        raise ConfigError(f"ERROR: Missing {field_name} in config.local.yaml")
    if not isinstance(value, dict):
        raise ConfigError(f"ERROR: {field_name} must be a YAML mapping")
    return value


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    root: dict[str, Any] = {}
    stack: list[Any] = [(-1, root)]

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


def next_container_kind(lines: list[str], start_index: int, current_indent: int) -> type | None:
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
