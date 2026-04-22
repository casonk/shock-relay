from __future__ import annotations

import sys
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
DYNO_LAB_SRC = REPO_ROOT.parent / "dyno-lab" / "src"
if str(DYNO_LAB_SRC) not in sys.path:
    sys.path.insert(0, str(DYNO_LAB_SRC))

from dyno_lab.module import load_module_by_path


class _DummySmtpClient:
    def __init__(self) -> None:
        self.message = None
        self.from_addr = ""
        self.to_addrs: list[str] = []

    def __enter__(self) -> _DummySmtpClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def send_message(self, message, from_addr, to_addrs) -> None:
        self.message = message
        self.from_addr = from_addr
        self.to_addrs = list(to_addrs)


class ShockRelayGmailHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gmail_common = load_module_by_path(
            REPO_ROOT / "services/gmail-imap/common.py",
            module_name="shock_relay_gmail_headers_common_test",
        )

    def _config(self):
        tls = self.gmail_common.TlsSettings(ca_cert_path="", insecure_skip_verify=False)
        imap = self.gmail_common.ImapSettings(
            host="imap.gmail.com",
            port=993,
            use_ssl=True,
            username="me@example.com",
            password="app-password",
            mailboxes=["INBOX"],
            readonly=True,
            timeout_seconds=30,
            poll_interval_seconds=60,
            search_charset=None,
            tls=tls,
        )
        smtp = self.gmail_common.SmtpSettings(
            host="smtp.gmail.com",
            port=465,
            use_ssl=True,
            starttls=False,
            username="me@example.com",
            password="app-password",
            from_address="me@example.com",
            timeout_seconds=30,
            allowed_recipients=[],
            tls=tls,
        )
        filters = self.gmail_common.InboxFilters(
            unseen_only=False,
            from_contains="",
            subject_contains="",
        )
        return self.gmail_common.GmailImapConfig(
            config_path="/tmp/config.local.yaml",
            imap=imap,
            smtp=smtp,
            filters=filters,
        )

    def test_parse_custom_header_args(self) -> None:
        headers = self.gmail_common.parse_custom_header_args(
            [
                "X-Portfolio-Service: intake",
                "X-Crew-Chief-Intent: notify",
            ]
        )
        self.assertEqual(
            headers,
            {
                "X-Portfolio-Service": "intake",
                "X-Crew-Chief-Intent": "notify",
            },
        )

    def test_parse_custom_header_args_requires_colon(self) -> None:
        with self.assertRaises(self.gmail_common.ConfigError):
            self.gmail_common.parse_custom_header_args(["X-Crew-Chief-Intent notify"])

    def test_send_email_includes_custom_headers(self) -> None:
        client = _DummySmtpClient()
        with patch.object(
            self.gmail_common, "open_smtp_connection", return_value=client
        ):
            payload = self.gmail_common.send_email(
                self._config(),
                to_addresses=["dest@example.com"],
                subject="subject",
                body="body",
                headers={
                    "X-Portfolio-Service": "crew-chief",
                    "X-Crew-Chief-Intent": "response",
                },
            )

        self.assertEqual(payload["headers"]["X-Portfolio-Service"], "crew-chief")
        self.assertEqual(payload["headers"]["X-Crew-Chief-Intent"], "response")
        self.assertIsNotNone(client.message)
        self.assertEqual(client.message["X-Portfolio-Service"], "crew-chief")
        self.assertEqual(client.message["X-Crew-Chief-Intent"], "response")
        self.assertEqual(client.to_addrs, ["dest@example.com"])

    def test_normalize_message_exposes_headers(self) -> None:
        message = EmailMessage()
        message["From"] = "intake@example.com"
        message["To"] = "me@example.com"
        message["Subject"] = "[intake] Receipt processed"
        message["Date"] = "Fri, 10 Apr 2026 18:10:00 +0000"
        message["Message-ID"] = "<msg@example.com>"
        message["X-Portfolio-Service"] = "intake"
        message["X-Crew-Chief-Intent"] = "notify"
        message.set_content("Receipt processed")

        normalized = self.gmail_common.normalize_message(
            "INBOX", 17, message.as_bytes()
        )

        self.assertEqual(normalized["headers"]["X-Portfolio-Service"], "intake")
        self.assertEqual(normalized["headers"]["X-Crew-Chief-Intent"], "notify")
        self.assertEqual(normalized["text"], "Receipt processed")


if __name__ == "__main__":
    unittest.main()
