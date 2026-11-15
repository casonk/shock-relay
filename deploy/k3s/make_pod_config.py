"""Turn the host's Gmail config into a pod config plus the environment file holding its credentials.

The pod cannot reach the vault, so credentials are resolved here, on the host, with shock-relay's own
loader (``common.load_config``), then handed to the pod as environment variables through a Secret. The pod's
config names those variables instead of vault entries, and carries no credential at all.

    make_pod_config.py --live services/gmail-imap/config.local.yaml --out DIR

writes DIR/config.yaml (mode 0600) and DIR/env (mode 0600) and prints only what it wrote, never a value.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
GMAIL_DIR = REPO / "services" / "gmail-imap"

ENV = {
    "imap_username": "SHOCK_RELAY_IMAP_USERNAME",
    "imap_password": "SHOCK_RELAY_IMAP_PASSWORD",
    "smtp_username": "SHOCK_RELAY_SMTP_USERNAME",
    "smtp_password": "SHOCK_RELAY_SMTP_PASSWORD",
    "smtp_from": "SHOCK_RELAY_SMTP_FROM",
}
CREDENTIAL_KEYS = (
    "username",
    "password",
    "from",
    "username_keepass_entry",
    "password_keepass_entry",
    "username_env",
    "password_env",
    "from_env",
)
POD_DATA_DIR = "/tmp/gmail-imap"
_PLAIN = re.compile(r"^[A-Za-z0-9_./:@+-]+$")


def pod_config(live: dict[str, Any]) -> dict[str, Any]:
    """The live config with every credential or vault entry replaced by an environment variable name."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in live.items()}
    out.pop("keepass_profile", None)
    imap = out.setdefault("imap", {})
    smtp = out.setdefault("smtp", {})
    for section in (imap, smtp):
        for key in CREDENTIAL_KEYS:
            section.pop(key, None)
    imap["username_env"], imap["password_env"] = ENV["imap_username"], ENV["imap_password"]
    smtp["username_env"], smtp["password_env"] = ENV["smtp_username"], ENV["smtp_password"]
    smtp["from_env"] = ENV["smtp_from"]
    out.setdefault("paths", {})["data_dir"] = POD_DATA_DIR
    return out


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    return (
        text if _PLAIN.match(text) else '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    )


def dump_yaml(data: dict[str, Any], indent: int = 0) -> str:
    """The subset of YAML shock-relay's own ``parse_simple_yaml`` reads: nested maps, scalar lists, scalars."""
    pad = "  " * indent
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(dump_yaml(value, indent + 1).rstrip("\n") or f"{pad}  ")
        elif isinstance(value, list):
            if not value:
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}:")
                lines.extend(f"{pad}  - {_scalar(item)}" for item in value)
        else:
            lines.append(f"{pad}{key}: {_scalar(value)}".rstrip())
    return "\n".join(lines) + "\n"


def environment(resolved: Any) -> dict[str, str]:
    """Credentials as the pod will read them. SMTP defaults to the IMAP account, as the loader does."""
    smtp_user = resolved.smtp.username or resolved.imap.username
    smtp_password = resolved.smtp.password or resolved.imap.password
    values = {
        ENV["imap_username"]: resolved.imap.username,
        ENV["imap_password"]: resolved.imap.password,
        ENV["smtp_username"]: smtp_user,
        ENV["smtp_password"]: smtp_password,
        ENV["smtp_from"]: resolved.smtp.from_address or smtp_user,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SystemExit(
            "could not resolve: " + ", ".join(sorted(missing)) + " (is the vault unlocked?)"
        )
    return values


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--live", type=Path, required=True, help="the host config (config.local.yaml)"
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="an owner-only directory to write into"
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(GMAIL_DIR))
    from common import load_config, parse_simple_yaml  # noqa: PLC0415  (shock-relay's own loader)

    live = parse_simple_yaml(args.live.read_text(encoding="utf-8"))
    values = environment(load_config(str(args.live)))
    args.out.mkdir(parents=True, exist_ok=True)
    _write_private(args.out / "config.yaml", dump_yaml(pod_config(live)))
    _write_private(args.out / "env", "".join(f"{k}={v}\n" for k, v in values.items()))
    print(
        f"wrote {args.out / 'config.yaml'} and {args.out / 'env'} ({len(values)} credential variables)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
