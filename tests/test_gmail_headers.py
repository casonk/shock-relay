from __future__ import annotations

import sys
import unittest
from email.message import EmailMessage
import imaplib
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
DYNO_LAB_SRC = REPO_ROOT.parent / "dyno-lab" / "src"
if str(DYNO_LAB_SRC) not in sys.path:
    sys.path.insert(0, str(DYNO_LAB_SRC))

from dyno_lab.module import load_module_by_path


class _DummySmtpClient:
    def __init__(self, *, send_result=None) -> None:
        self.message = None
        self.from_addr = ""
        self.to_addrs: list[str] = []
        self.send_result = send_result or {}

    def __enter__(self) -> _DummySmtpClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def send_message(self, message, from_addr, to_addrs):
        self.message = message
        self.from_addr = from_addr
        self.to_addrs = list(to_addrs)
        return self.send_result


class _DummyImapClient:
    def __init__(
        self,
        *,
        select_result=("OK", [b"1"]),
        search_result=("OK", [b"17"]),
        fetch_result=None,
    ) -> None:
        self.select_result = select_result
        self.search_result = search_result
        self.fetch_result = fetch_result or (
            "OK",
            [(b"17 (RFC822 {1})", self._message_bytes())],
        )

    def __enter__(self) -> _DummyImapClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def select(self, mailbox, readonly=True):
        if isinstance(self.select_result, BaseException):
            raise self.select_result
        return self.select_result

    def uid(self, command, *args):
        if command == "search":
            if isinstance(self.search_result, BaseException):
                raise self.search_result
            return self.search_result
        if command == "fetch":
            if isinstance(self.fetch_result, BaseException):
                raise self.fetch_result
            return self.fetch_result
        raise AssertionError(f"unexpected IMAP uid command: {command}")

    @staticmethod
    def _message_bytes() -> bytes:
        message = EmailMessage()
        message["From"] = "sender@example.com"
        message["To"] = "me@example.com"
        message["Subject"] = "subject"
        message["Date"] = "Fri, 10 Apr 2026 18:10:00 +0000"
        message["Message-ID"] = "<msg@example.com>"
        message.set_content("body")
        return message.as_bytes()


class _VerifyImapClient:
    def __init__(
        self,
        *,
        sent_mailboxes: list[str] | None = None,
        messages_by_mailbox: dict[str, list[tuple[int, bytes]]] | None = None,
    ) -> None:
        self.sent_mailboxes = sent_mailboxes or ["[Gmail]/Sent Mail"]
        self.messages_by_mailbox = messages_by_mailbox or {}
        self.selected_mailbox = ""

    def __enter__(self) -> _VerifyImapClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def list(self):
        payload = []
        for mailbox in self.sent_mailboxes:
            payload.append(f'(\\HasNoChildren \\Sent) "/" "{mailbox}"'.encode("utf-8"))
        return ("OK", payload)

    def select(self, mailbox, readonly=True):
        self.selected_mailbox = mailbox
        if mailbox not in self.messages_by_mailbox:
            return ("NO", [b"missing"])
        return ("OK", [str(len(self.messages_by_mailbox[mailbox])).encode("utf-8")])

    def uid(self, command, *args):
        if command == "search":
            items = self.messages_by_mailbox.get(self.selected_mailbox, [])
            uid_bytes = b" ".join(str(uid).encode("utf-8") for uid, _ in items)
            return ("OK", [uid_bytes])
        if command == "fetch":
            requested_uid = int(str(args[0]))
            items = dict(self.messages_by_mailbox.get(self.selected_mailbox, []))
            payload = items.get(requested_uid, b"")
            return ("OK", [(b"1 (RFC822 {1})", payload)])
        raise AssertionError(f"unexpected IMAP uid command: {command}")


class _QuotedMailboxVerifyImapClient(_VerifyImapClient):
    def select(self, mailbox, readonly=True):
        normalized_mailbox = (
            mailbox[1:-1]
            if mailbox.startswith('"') and mailbox.endswith('"')
            else mailbox
        )
        self.selected_mailbox = normalized_mailbox
        if " " in mailbox and not mailbox.startswith('"'):
            return ("NO", [b"quote required"])
        if normalized_mailbox not in self.messages_by_mailbox:
            return ("NO", [b"missing"])
        return (
            "OK",
            [str(len(self.messages_by_mailbox[normalized_mailbox])).encode("utf-8")],
        )


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
            verify_delivery=True,
            verify_attempts=4,
            verify_delay_seconds=2,
            verify_recent_limit=10,
            verify_mailboxes=[],
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
        verify_client = _VerifyImapClient(
            messages_by_mailbox={
                "[Gmail]/Sent Mail": [
                    (17, self._build_message_bytes(message_id="<verified@example.com>"))
                ]
            }
        )
        with (
            patch.object(
                self.gmail_common, "make_msgid", return_value="<verified@example.com>"
            ),
            patch.object(
                self.gmail_common, "open_smtp_connection", return_value=client
            ),
            patch.object(
                self.gmail_common, "open_imap_connection", return_value=verify_client
            ),
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
        self.assertTrue(payload["delivery"]["verified"])
        self.assertEqual(payload["delivery"]["mailbox"], "[Gmail]/Sent Mail")
        self.assertIsNotNone(client.message)
        self.assertEqual(client.message["X-Portfolio-Service"], "crew-chief")
        self.assertEqual(client.message["X-Crew-Chief-Intent"], "response")
        self.assertEqual(client.to_addrs, ["dest@example.com"])

    def test_send_email_raises_for_rejected_recipients(self) -> None:
        client = _DummySmtpClient(
            send_result={"dest@example.com": (550, b"Mailbox unavailable")}
        )
        with patch.object(
            self.gmail_common, "open_smtp_connection", return_value=client
        ):
            with self.assertRaises(self.gmail_common.MailError) as ctx:
                self.gmail_common.send_email(
                    self._config(),
                    to_addresses=["dest@example.com"],
                    subject="subject",
                    body="body",
                )

        self.assertIn("dest@example.com", str(ctx.exception))
        self.assertIn("550", str(ctx.exception))

    def test_send_email_retries_delivery_verification(self) -> None:
        client = _DummySmtpClient()
        first_verify = _VerifyImapClient(messages_by_mailbox={})
        second_verify = _VerifyImapClient(
            messages_by_mailbox={
                "[Gmail]/Sent Mail": [
                    (17, self._build_message_bytes(message_id="<retry@example.com>"))
                ]
            }
        )
        with (
            patch.object(
                self.gmail_common, "make_msgid", return_value="<retry@example.com>"
            ),
            patch.object(
                self.gmail_common, "open_smtp_connection", return_value=client
            ),
            patch.object(
                self.gmail_common,
                "open_imap_connection",
                side_effect=[first_verify, second_verify],
            ) as open_imap_mock,
            patch.object(self.gmail_common.time, "sleep") as sleep_mock,
        ):
            payload = self.gmail_common.send_email(
                self._config(),
                to_addresses=["dest@example.com"],
                subject="subject",
                body="body",
            )

        self.assertTrue(payload["delivery"]["verified"])
        self.assertEqual(payload["delivery"]["attempts"], 2)
        self.assertEqual(open_imap_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2)

    def test_send_email_verification_quotes_mailbox_names_with_spaces(self) -> None:
        client = _DummySmtpClient()
        verify_client = _QuotedMailboxVerifyImapClient(
            messages_by_mailbox={
                "[Gmail]/Sent Mail": [
                    (17, self._build_message_bytes(message_id="<quoted@example.com>"))
                ]
            }
        )
        with (
            patch.object(
                self.gmail_common, "make_msgid", return_value="<quoted@example.com>"
            ),
            patch.object(
                self.gmail_common, "open_smtp_connection", return_value=client
            ),
            patch.object(
                self.gmail_common, "open_imap_connection", return_value=verify_client
            ),
        ):
            payload = self.gmail_common.send_email(
                self._config(),
                to_addresses=["dest@example.com"],
                subject="subject",
                body="body",
            )

        self.assertTrue(payload["delivery"]["verified"])
        self.assertEqual(payload["delivery"]["mailbox"], "[Gmail]/Sent Mail")

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

    def test_list_messages_retries_transient_imap_abort_and_succeeds(self) -> None:
        first = _DummyImapClient(
            select_result=imaplib.IMAP4.abort("command: EXAMINE => System Error")
        )
        second = _DummyImapClient()
        with (
            patch.object(
                self.gmail_common,
                "open_imap_connection",
                side_effect=[first, second],
            ) as open_mock,
            patch.object(self.gmail_common.time, "sleep") as sleep_mock,
        ):
            payload = self.gmail_common.list_messages(self._config(), limit=1)

        self.assertEqual(len(payload["messages"]), 1)
        self.assertEqual(open_mock.call_count, 2)
        sleep_mock.assert_called_once()

    def test_list_messages_reports_context_after_retry_exhaustion(self) -> None:
        transient = imaplib.IMAP4.abort("command: UID => System Error")
        failing_clients = [
            _DummyImapClient(search_result=transient),
            _DummyImapClient(search_result=transient),
            _DummyImapClient(search_result=transient),
        ]
        with (
            patch.object(
                self.gmail_common,
                "open_imap_connection",
                side_effect=failing_clients,
            ),
            patch.object(self.gmail_common.time, "sleep"),
        ):
            with self.assertRaises(self.gmail_common.MailError) as ctx:
                self.gmail_common.list_messages(self._config(), limit=1)

        message = str(ctx.exception)
        self.assertIn("after 3 attempt(s)", message)
        self.assertIn("host=imap.gmail.com:993", message)
        self.assertIn("mailboxes=INBOX", message)
        self.assertIn("UID => System Error", message)

    @staticmethod
    def _build_message_bytes(message_id: str) -> bytes:
        message = EmailMessage()
        message["From"] = "me@example.com"
        message["To"] = "dest@example.com"
        message["Subject"] = "subject"
        message["Date"] = "Fri, 10 Apr 2026 18:10:00 +0000"
        message["Message-ID"] = message_id
        message.set_content("body")
        return message.as_bytes()


if __name__ == "__main__":
    unittest.main()
