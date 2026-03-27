#!/usr/bin/env python3
import imaplib
import os
import re
import socket
import smtplib
import ssl
from dataclasses import dataclass
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import formatdate, make_msgid, parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


class ConfigError(RuntimeError):
    pass


class MailError(RuntimeError):
    pass


@dataclass
class TlsSettings:
    ca_cert_path: str
    insecure_skip_verify: bool


@dataclass
class ImapSettings:
    host: str
    port: int
    use_ssl: bool
    username: str
    password: str
    mailboxes: List[str]
    readonly: bool
    timeout_seconds: int
    poll_interval_seconds: int
    search_charset: Optional[str]
    tls: TlsSettings


@dataclass
class SmtpSettings:
    host: str
    port: int
    use_ssl: bool
    starttls: bool
    username: str
    password: str
    from_address: str
    timeout_seconds: int
    allowed_recipients: List[str]
    tls: TlsSettings


@dataclass
class InboxFilters:
    unseen_only: bool
    from_contains: str
    subject_contains: str


@dataclass
class GmailImapConfig:
    config_path: str
    imap: ImapSettings
    smtp: SmtpSettings
    filters: InboxFilters


def default_config_path() -> str:
    return os.environ.get(
        "GMAIL_IMAP_LOCAL_CONFIG",
        str(Path(__file__).resolve().parent / "config.local.yaml"),
    )


def load_config(config_path: str) -> GmailImapConfig:
    try:
        config_text = Path(config_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"ERROR: Cannot read config file: {config_path} ({exc})") from exc

    config = parse_simple_yaml(config_text)
    imap_cfg = as_mapping(config.get("imap"), "imap")
    smtp_cfg = as_mapping(config.get("smtp"), "smtp", allow_empty=True)
    filters_cfg = as_mapping(config.get("filters"), "filters", allow_empty=True)

    imap_tls_cfg = as_mapping(imap_cfg.get("tls"), "imap.tls", allow_empty=True)
    smtp_tls_cfg = as_mapping(smtp_cfg.get("tls"), "smtp.tls", allow_empty=True)

    imap_use_ssl = parse_bool(imap_cfg.get("use_ssl"), default=True, field_name="imap.use_ssl")
    imap_host = optional_string(imap_cfg.get("host")) or "imap.gmail.com"
    imap_port = parse_int(
        imap_cfg.get("port"),
        default=993 if imap_use_ssl else 143,
        field_name="imap.port",
    )
    imap_username = optional_string(imap_cfg.get("username")) or resolve_env_value(
        optional_string(imap_cfg.get("username_env")),
        field_name="imap.username_env",
        required=False,
    )
    imap_password = optional_string(imap_cfg.get("password")) or resolve_env_value(
        optional_string(imap_cfg.get("password_env")),
        field_name="imap.password_env",
        required=False,
    )
    imap_timeout_seconds = parse_int(
        imap_cfg.get("timeout_seconds"),
        default=30,
        field_name="imap.timeout_seconds",
    )
    imap_poll_interval_seconds = parse_int(
        imap_cfg.get("poll_interval_seconds"),
        default=60,
        field_name="imap.poll_interval_seconds",
    )
    imap_readonly = parse_bool(imap_cfg.get("readonly"), default=True, field_name="imap.readonly")
    imap_search_charset = optional_string(imap_cfg.get("search_charset")) or None
    imap_mailboxes = resolve_imap_mailboxes(imap_cfg)
    imap_tls = load_tls_settings(imap_tls_cfg, prefix="imap.tls")

    smtp_use_ssl = parse_bool(smtp_cfg.get("use_ssl"), default=True, field_name="smtp.use_ssl")
    smtp_starttls = parse_bool(smtp_cfg.get("starttls"), default=False, field_name="smtp.starttls")
    if smtp_use_ssl and smtp_starttls:
        raise ConfigError("ERROR: Configure either smtp.use_ssl or smtp.starttls, not both")
    smtp_host = optional_string(smtp_cfg.get("host")) or "smtp.gmail.com"
    smtp_port = parse_int(
        smtp_cfg.get("port"),
        default=465 if smtp_use_ssl else 587,
        field_name="smtp.port",
    )
    smtp_username = optional_string(smtp_cfg.get("username")) or resolve_env_value(
        optional_string(smtp_cfg.get("username_env")),
        field_name="smtp.username_env",
        required=False,
    )
    if not smtp_username:
        smtp_username = imap_username
    smtp_password = optional_string(smtp_cfg.get("password")) or resolve_env_value(
        optional_string(smtp_cfg.get("password_env")),
        field_name="smtp.password_env",
        required=False,
    )
    if not smtp_password:
        smtp_password = imap_password
    smtp_from_address = optional_string(smtp_cfg.get("from")) or resolve_env_value(
        optional_string(smtp_cfg.get("from_env")),
        field_name="smtp.from_env",
        required=False,
    )
    if not smtp_from_address:
        smtp_from_address = smtp_username
    smtp_timeout_seconds = parse_int(
        smtp_cfg.get("timeout_seconds"),
        default=30,
        field_name="smtp.timeout_seconds",
    )
    smtp_allowed_recipients = read_allowed_recipients(smtp_cfg)
    smtp_tls = load_tls_settings(smtp_tls_cfg, prefix="smtp.tls")

    return GmailImapConfig(
        config_path=config_path,
        imap=ImapSettings(
            host=imap_host,
            port=imap_port,
            use_ssl=imap_use_ssl,
            username=imap_username,
            password=imap_password,
            mailboxes=imap_mailboxes,
            readonly=imap_readonly,
            timeout_seconds=imap_timeout_seconds,
            poll_interval_seconds=imap_poll_interval_seconds,
            search_charset=imap_search_charset,
            tls=imap_tls,
        ),
        smtp=SmtpSettings(
            host=smtp_host,
            port=smtp_port,
            use_ssl=smtp_use_ssl,
            starttls=smtp_starttls,
            username=smtp_username,
            password=smtp_password,
            from_address=smtp_from_address,
            timeout_seconds=smtp_timeout_seconds,
            allowed_recipients=smtp_allowed_recipients,
            tls=smtp_tls,
        ),
        filters=InboxFilters(
            unseen_only=parse_bool(filters_cfg.get("unseen_only"), default=False, field_name="filters.unseen_only"),
            from_contains=optional_string(filters_cfg.get("from_contains")),
            subject_contains=optional_string(filters_cfg.get("subject_contains")),
        ),
    )


def send_email(
    config: GmailImapConfig,
    to_addresses: List[str],
    subject: str,
    body: str,
    cc_addresses: Optional[List[str]] = None,
    bcc_addresses: Optional[List[str]] = None,
) -> Dict[str, Any]:
    validate_smtp(config)
    normalized_to = normalize_email_list(to_addresses)
    normalized_cc = normalize_email_list(cc_addresses or [])
    normalized_bcc = normalize_email_list(bcc_addresses or [])

    if not normalized_to:
        raise ConfigError("ERROR: At least one recipient email address is required")

    all_recipients = normalized_to + normalized_cc + normalized_bcc
    validate_recipients(config, all_recipients)

    message = EmailMessage()
    message["From"] = config.smtp.from_address
    message["To"] = ", ".join(normalized_to)
    if normalized_cc:
        message["Cc"] = ", ".join(normalized_cc)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid()
    message.set_content(body)

    try:
        with open_smtp_connection(config) as client:
            client.send_message(message, from_addr=config.smtp.from_address, to_addrs=all_recipients)
    except MailError:
        raise
    except Exception as exc:
        raise MailError(f"SMTP send failed: {type(exc).__name__}: {exc}") from exc

    return {
        "message_id": str(message.get("Message-ID") or ""),
        "from": config.smtp.from_address,
        "to": normalized_to,
        "cc": normalized_cc,
        "bcc": normalized_bcc,
        "subject": subject,
    }


def list_messages(
    config: GmailImapConfig,
    mailboxes: Optional[List[str]] = None,
    limit: int = 20,
    unseen_only: Optional[bool] = None,
    from_contains: Optional[str] = None,
    subject_contains: Optional[str] = None,
    since_days: Optional[int] = None,
) -> Dict[str, Any]:
    validate_imap(config)
    selected_mailboxes = normalize_mailboxes(mailboxes or config.imap.mailboxes)
    effective_unseen_only = config.filters.unseen_only if unseen_only is None else unseen_only
    effective_from_contains = (from_contains if from_contains is not None else config.filters.from_contains).strip()
    effective_subject_contains = (
        subject_contains if subject_contains is not None else config.filters.subject_contains
    ).strip()
    effective_limit = max(1, limit)

    messages: List[Dict[str, Any]] = []
    try:
        with open_imap_connection(config) as conn:
            for mailbox in selected_mailboxes:
                status, _ = conn.select(mailbox, readonly=config.imap.readonly)
                if status != "OK":
                    raise MailError(f"IMAP mailbox select failed: {mailbox} ({status})")

                search_terms = build_search_terms(
                    unseen_only=effective_unseen_only,
                    from_contains=effective_from_contains,
                    subject_contains=effective_subject_contains,
                    since_days=since_days,
                )
                status, data = conn.uid("search", config.imap.search_charset, *search_terms)
                if status != "OK":
                    raise MailError(f"IMAP UID search failed in {mailbox}: {status}")

                uids = parse_int_uid_list(data)
                if not uids:
                    continue

                for uid in reversed(uids[-effective_limit:]):
                    status, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
                    if status != "OK":
                        raise MailError(f"IMAP UID fetch failed for {uid} in {mailbox}: {status}")
                    payload_bytes = extract_fetch_payload(msg_data)
                    if not payload_bytes:
                        continue
                    messages.append(normalize_message(mailbox, uid, payload_bytes))
    except MailError:
        raise
    except Exception as exc:
        raise MailError(f"IMAP inbox check failed: {type(exc).__name__}: {exc}") from exc

    messages.sort(
        key=lambda item: (
            item.get("timestamp") or 0,
            int(item.get("uid") or 0),
        ),
        reverse=True,
    )
    return {
        "messages": messages[:effective_limit],
    }


def test_imap_connection(config: GmailImapConfig, mailbox: Optional[str] = None) -> Dict[str, Any]:
    validate_imap(config)
    selected_mailbox = mailbox or config.imap.mailboxes[0]
    try:
        with open_imap_connection(config) as conn:
            status, data = conn.select(selected_mailbox, readonly=True)
            if status != "OK":
                raise MailError(f"IMAP mailbox select failed: {selected_mailbox} ({status})")
    except MailError:
        raise
    except Exception as exc:
        raise MailError(f"IMAP connection test failed: {type(exc).__name__}: {exc}") from exc
    return {
        "host": config.imap.host,
        "port": config.imap.port,
        "mailbox": selected_mailbox,
        "status": "ok",
        "message_count": parse_exists_count(data),
    }


def test_smtp_connection(config: GmailImapConfig) -> Dict[str, Any]:
    validate_smtp(config)
    try:
        with open_smtp_connection(config) as client:
            status = client.noop()
    except MailError:
        raise
    except Exception as exc:
        raise MailError(f"SMTP connection test failed: {type(exc).__name__}: {exc}") from exc
    smtp_status = ""
    if isinstance(status, tuple) and status:
        smtp_status = str(status[0])
    return {
        "host": config.smtp.host,
        "port": config.smtp.port,
        "from": config.smtp.from_address,
        "status": smtp_status or "ok",
    }


def open_imap_connection(config: GmailImapConfig):
    validate_imap(config)
    connection = None
    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(config.imap.timeout_seconds)
        ssl_context = build_ssl_context(config.imap.tls)
        if config.imap.use_ssl:
            ssl_kwargs = {}
            if ssl_context is not None:
                ssl_kwargs["ssl_context"] = ssl_context
            try:
                connection = imaplib.IMAP4_SSL(
                    config.imap.host,
                    config.imap.port,
                    timeout=config.imap.timeout_seconds,
                    **ssl_kwargs,
                )
            except TypeError:
                connection = imaplib.IMAP4_SSL(
                    config.imap.host,
                    config.imap.port,
                    **ssl_kwargs,
                )
        else:
            try:
                connection = imaplib.IMAP4(
                    config.imap.host,
                    config.imap.port,
                    timeout=config.imap.timeout_seconds,
                )
            except TypeError:
                connection = imaplib.IMAP4(
                    config.imap.host,
                    config.imap.port,
                )
        status, _ = connection.login(config.imap.username, config.imap.password)
        if status != "OK":
            raise MailError(f"IMAP login failed: {status}")
    except MailError:
        try:
            if connection is not None:
                connection.logout()
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            if connection is not None:
                connection.logout()
        except Exception:
            pass
        raise MailError(f"IMAP connection failed: {type(exc).__name__}: {exc}") from exc
    finally:
        socket.setdefaulttimeout(previous_timeout)
    return connection


def open_smtp_connection(config: GmailImapConfig):
    validate_smtp(config)
    context = build_ssl_context(config.smtp.tls)
    client = None
    try:
        if config.smtp.use_ssl:
            client = smtplib.SMTP_SSL(
                config.smtp.host,
                config.smtp.port,
                timeout=config.smtp.timeout_seconds,
                context=context,
            )
        else:
            client = smtplib.SMTP(
                config.smtp.host,
                config.smtp.port,
                timeout=config.smtp.timeout_seconds,
            )
            client.ehlo()
            if config.smtp.starttls:
                client.starttls(context=context)
                client.ehlo()
        if config.smtp.username:
            client.login(config.smtp.username, config.smtp.password)
    except Exception as exc:
        try:
            if client is not None:
                client.quit()
        except Exception:
            pass
        raise MailError(f"SMTP connection failed: {type(exc).__name__}: {exc}") from exc
    return client


def normalize_message(mailbox: str, uid: int, payload_bytes: bytes) -> Dict[str, Any]:
    message = message_from_bytes(payload_bytes, policy=default_policy)
    subject = decode_mime_header(message.get("Subject"))
    sender = decode_mime_header(message.get("From"))
    to_header = decode_mime_header(message.get("To"))
    cc_header = decode_mime_header(message.get("Cc"))
    date_header = str(message.get("Date", "") or "").strip()
    text_body, html_body = extract_message_bodies(message)
    combined_text = text_body or html_body or ""

    return {
        "uid": uid,
        "mailbox": mailbox,
        "message_id": decode_mime_header(message.get("Message-ID")),
        "date": date_header,
        "timestamp": parse_date_epoch(date_header),
        "from": sender,
        "to": to_header,
        "cc": cc_header,
        "subject": subject,
        "snippet": combined_text[:500],
        "text": text_body,
        "html": html_body,
    }


def extract_message_bodies(message: Any) -> Tuple[str, str]:
    text_parts: List[str] = []
    html_parts: List[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_type = str(part.get_content_type() or "")
            disposition = str(part.get_content_disposition() or "")
            if disposition == "attachment":
                continue
            if content_type not in {"text/plain", "text/html"}:
                continue
            decoded = decode_part_text(part)
            if not decoded:
                continue
            if content_type == "text/plain":
                text_parts.append(decoded)
            else:
                html_parts.append(decoded)
    else:
        decoded = decode_part_text(message)
        if str(message.get_content_type() or "") == "text/html":
            html_parts.append(decoded)
        else:
            text_parts.append(decoded)

    return "\n".join(filter(None, text_parts)).strip(), "\n".join(filter(None, html_parts)).strip()


def decode_part_text(part: Any) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        payload = None
    if payload is None:
        raw_payload = part.get_payload()
        if isinstance(raw_payload, str):
            return raw_payload
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def decode_mime_header(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def parse_date_epoch(value: str) -> Optional[int]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    try:
        return int(parsed.timestamp())
    except Exception:
        return None


def build_search_terms(
    unseen_only: bool = False,
    from_contains: str = "",
    subject_contains: str = "",
    since_days: Optional[int] = None,
) -> List[str]:
    terms: List[str] = []
    if unseen_only:
        terms.append("UNSEEN")
    if from_contains:
        terms.extend(["FROM", f'"{from_contains}"'])
    if subject_contains:
        terms.extend(["SUBJECT", f'"{subject_contains}"'])
    if since_days is not None and since_days >= 0:
        from datetime import datetime, timedelta, timezone

        since_date = datetime.now(timezone.utc) - timedelta(days=since_days)
        terms.extend(["SINCE", since_date.strftime("%d-%b-%Y")])
    if not terms:
        return ["ALL"]
    return terms


def resolve_imap_mailboxes(imap_cfg: Dict[str, Any]) -> List[str]:
    configured = read_scalar_list(imap_cfg.get("mailboxes"), "imap.mailboxes")
    mailbox = optional_string(imap_cfg.get("mailbox")) or "INBOX"
    return normalize_mailboxes([mailbox] + configured)


def normalize_mailboxes(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        mailbox = str(value or "").strip() or "INBOX"
        key = mailbox.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(mailbox)
    return result or ["INBOX"]


def normalize_email_list(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in values:
        for candidate in split_values(str(item)):
            _, address = parseaddr(candidate)
            normalized = address.strip().lower()
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
    return result


def validate_recipients(config: GmailImapConfig, recipients: List[str]) -> None:
    if not config.smtp.allowed_recipients:
        return
    allowed = {canonical_email(item) for item in config.smtp.allowed_recipients}
    for recipient in recipients:
        if canonical_email(recipient) not in allowed:
            raise ConfigError(f"ERROR: Recipient is not allowed by smtp.allowed_recipients: {recipient}")


def canonical_email(value: Any) -> str:
    _, address = parseaddr(str(value or ""))
    return address.strip().lower()


def validate_imap(config: GmailImapConfig) -> None:
    if not config.imap.username:
        raise ConfigError("ERROR: Missing imap.username or imap.username_env in config.local.yaml")
    if not config.imap.password:
        raise ConfigError("ERROR: Missing imap.password or imap.password_env in config.local.yaml")
    if not config.imap.host:
        raise ConfigError("ERROR: Missing imap.host in config.local.yaml")


def validate_smtp(config: GmailImapConfig) -> None:
    if not config.smtp.host:
        raise ConfigError("ERROR: Missing smtp.host in config.local.yaml")
    if not config.smtp.from_address:
        raise ConfigError("ERROR: Missing smtp.from or smtp.from_env in config.local.yaml")
    if not config.smtp.username:
        raise ConfigError("ERROR: Missing smtp.username or smtp.username_env in config.local.yaml")
    if not config.smtp.password:
        raise ConfigError("ERROR: Missing smtp.password or smtp.password_env in config.local.yaml")


def load_tls_settings(tls_cfg: Dict[str, Any], prefix: str) -> TlsSettings:
    insecure_skip_verify = parse_bool(
        tls_cfg.get("insecure_skip_verify"),
        default=False,
        field_name=f"{prefix}.insecure_skip_verify",
    )
    ca_cert_path = optional_string(tls_cfg.get("ca_cert_path")) or resolve_env_value(
        optional_string(tls_cfg.get("ca_cert_path_env")),
        field_name=f"{prefix}.ca_cert_path_env",
        required=False,
    )
    if insecure_skip_verify and ca_cert_path:
        raise ConfigError(f"ERROR: Configure either {prefix}.insecure_skip_verify or a CA cert path, not both")
    if ca_cert_path and not Path(ca_cert_path).is_file():
        raise ConfigError(f"ERROR: CA certificate file does not exist: {ca_cert_path}")
    return TlsSettings(
        ca_cert_path=ca_cert_path,
        insecure_skip_verify=insecure_skip_verify,
    )


def build_ssl_context(tls: TlsSettings) -> Optional[ssl.SSLContext]:
    if tls.insecure_skip_verify:
        return ssl._create_unverified_context()
    if tls.ca_cert_path:
        return ssl.create_default_context(cafile=tls.ca_cert_path)
    return None


def parse_exists_count(data: Any) -> int:
    if not isinstance(data, list):
        return 0
    for item in data:
        if isinstance(item, bytes):
            try:
                return int(item.decode("utf-8", errors="ignore").strip())
            except ValueError:
                continue
    return 0


def extract_fetch_payload(msg_data: Any) -> bytes:
    if not isinstance(msg_data, list):
        return b""
    for item in msg_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return b""


def parse_int_uid_list(data: Any) -> List[int]:
    if not isinstance(data, list):
        return []
    chunks: List[bytes] = []
    for item in data:
        if isinstance(item, bytes):
            chunks.append(item)
        elif item is not None:
            chunks.append(str(item).encode("utf-8"))
    combined = b" ".join(chunks).strip()
    if not combined:
        return []
    result: List[int] = []
    for token in combined.split():
        token_text = token.decode("utf-8", errors="ignore")
        if re.fullmatch(r"\d+", token_text):
            result.append(int(token_text))
    return result


def read_allowed_recipients(smtp_cfg: Dict[str, Any]) -> List[str]:
    recipients = read_scalar_list(smtp_cfg.get("allowed_recipients"), "smtp.allowed_recipients")
    env_names = read_scalar_list(smtp_cfg.get("allowed_recipient_envs"), "smtp.allowed_recipient_envs")

    for env_name in env_names:
        raw_value = resolve_env_value(env_name, field_name=f"smtp.allowed_recipient_envs[{env_name}]")
        recipients.extend(split_values(raw_value))

    return normalize_email_list(recipients)


def split_values(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]


def read_scalar_list(value: Any, field_name: str) -> List[str]:
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


def resolve_env_value(env_name: Optional[str], field_name: str, required: bool = True) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name, "")
    if value:
        return value
    if required:
        raise ConfigError(f"ERROR: Environment variable {env_name} referenced by {field_name} is not set")
    return ""


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
