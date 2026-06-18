#!/usr/bin/env python3
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path


def extract_signal_cli_fields(config_path: str) -> tuple[str, str, str]:
    """
    Extract (account, bus_name, linked_name) from:
      signal_cli:
        account: ...
        linked_name: ...
        bus_name: ...
    Avoids adding YAML dependencies.
    """
    try:
        txt = Path(config_path).read_text(encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"ERROR: Cannot read config file: {config_path} ({e})") from e

    def get_in_signal_cli(key: str) -> str:
        lines = txt.splitlines()
        in_block = False
        base_indent = None

        key_re = re.compile(
            rf"^\s*{re.escape(key)}:\s*(?:(\"([^\"]*)\")|('([^']*)')|([^\s#]+))\s*(?:#.*)?$"
        )

        for line in lines:
            if not in_block:
                if re.match(r"^\s*signal_cli:\s*$", line):
                    in_block = True
                    base_indent = len(line) - len(line.lstrip())
                continue

            if line.strip() != "":
                indent = len(line) - len(line.lstrip())
                if base_indent is not None and indent <= base_indent:
                    break

            m = key_re.match(line)
            if m:
                # groups: full, double-quoted, double-value, single-quoted, single-value, unquoted
                for group in m.groups()[1:]:
                    if group:
                        return group.strip()
        return ""

    account = get_in_signal_cli("account")
    bus_name = get_in_signal_cli("bus_name")
    linked_name = get_in_signal_cli("linked_name")

    if not account:
        raise RuntimeError("ERROR: Missing signal_cli.account in config.local.yaml")
    if not linked_name:
        raise RuntimeError("ERROR: Missing signal_cli.linked_name in config.local.yaml")

    return account, bus_name, linked_name


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def get_ip_address() -> str:
    # UDP connect does not send packets; it just selects an outbound interface.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        pass

    try:
        # hostname to IP may be slow; use best-effort.
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "unknown"


def main() -> int:
    service_dir = Path(__file__).resolve().parent
    config_path = os.environ.get("SIGNAL_CLI_LOCAL_CONFIG", str(service_dir / "config.local.yaml"))
    receive_timeout_seconds = int(os.environ.get("RECEIVE_TIMEOUT_SECONDS", "120"))
    message_text_override = os.environ.get("MESSAGE_TEXT_OVERRIDE", "")

    account, bus_name, linked_name = extract_signal_cli_fields(config_path)

    hostname = get_hostname().split(".")[0]
    ip_addr = get_ip_address()

    reg_token = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    test_payload = message_text_override or "hello from shock-relay test"

    test_message = "\n".join(
        [
            "shock-relay TEST",
            f"reg: {reg_token}",
            f"sender_linked_name: {linked_name}",
            f"computer_hostname: {hostname}",
            f"computer_ip: {ip_addr}",
            f"test_payload: {test_payload}",
            'Please reply with any message starting with "response:" (or just reply normally).',
        ]
    )

    signal_args = ["signal-cli", "-a", account]
    if bus_name:
        signal_args.extend(["--bus-name", bus_name])

    send_cmd = signal_args + ["send", "--note-to-self", "-m", test_message]
    print(f"Sending TEST message (reg={reg_token}) to self...")
    subprocess.run(send_cmd, check=True)

    start = time.monotonic()
    response_raw: str | None = None

    # Loop until we find a received message that does NOT contain our reg token.
    while True:
        elapsed = time.monotonic() - start
        remaining = receive_timeout_seconds - elapsed
        if remaining <= 0:
            print("ERROR: Timed out waiting for response.", file=sys.stderr)
            return 1

        # Receive one message at a time.
        receive_cmd = signal_args + [
            "receive",
            "--timeout",
            str(int(remaining) if remaining > 1 else 1),
            "--max-messages",
            "1",
            "--ignore-attachments",
            "--ignore-stories",
            "--ignore-avatars",
            "--ignore-stickers",
        ]
        proc = subprocess.run(receive_cmd, check=False, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        if not out.strip():
            continue

        if re.search(rf"reg:\s*{re.escape(reg_token)}", out):
            continue

        response_raw = out
        break

    response_trunc = response_raw[:2000] if response_raw else ""

    confirmation_message = "\n".join(
        [
            "shock-relay CONFIRMATION",
            f"reg: {reg_token}",
            f"sender_linked_name: {linked_name}",
            f"computer_hostname: {hostname}",
            f"computer_ip: {ip_addr}",
            "response_received: true",
            "",
            "response_output (truncated):",
            response_trunc,
        ]
    )

    confirm_cmd = signal_args + ["send", "--note-to-self", "-m", confirmation_message]
    print("Sending CONFIRMATION back to self...")
    subprocess.run(confirm_cmd, check=True)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
