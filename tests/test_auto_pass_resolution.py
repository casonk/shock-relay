from __future__ import annotations

import unittest
from pathlib import Path

from dyno_lab.auto_pass import AutoPassPatch, AutoPassRecorder
from dyno_lab.module import load_module_by_path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ShockRelayAutoPassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gmail_common = load_module_by_path(
            REPO_ROOT / "services/gmail-imap/common.py",
            module_name="shock_relay_gmail_common_test",
        )
        cls.twilio_common = load_module_by_path(
            REPO_ROOT / "services/twilio/common.py",
            module_name="shock_relay_twilio_common_test",
        )

    def test_gmail_keepass_resolution_loads_profile_and_falls_back_to_email_prefix(
        self,
    ) -> None:
        recorder = AutoPassRecorder()
        recorder.add_response(
            "example-account#imap",
            recorder.keepass_error("Entry example-account#imap was not found."),
        )
        recorder.add_response(
            "email/example-account#imap",
            {"value": "imap-secret"},
        )

        with AutoPassPatch(recorder):
            resolved = self.gmail_common._resolve_keepass_value(
                "example-account#imap",
                "password",
                "infra",
            )

        self.assertEqual(resolved, "imap-secret")
        self.assertEqual(recorder.load_calls[0].profile, "infra")
        self.assertTrue(
            str(recorder.load_calls[0].path).endswith("auto-pass/config/auto-pass.env.local")
        )
        self.assertEqual(
            [call.entry for call in recorder.resolve_calls],
            ["example-account#imap", "email/example-account#imap"],
        )
        self.assertEqual(recorder.resolve_calls[0].attrs_map, {"value": "password"})

    def test_twilio_keepass_resolution_loads_profile_and_falls_back_to_twilio_prefix(
        self,
    ) -> None:
        recorder = AutoPassRecorder()
        recorder.add_response(
            "Twilio/example-account#token",
            recorder.keepass_error("Entry Twilio/example-account#token was not found."),
        )
        recorder.add_response(
            "twilio/example-account#token",
            {"value": "twilio-secret"},
        )

        with AutoPassPatch(recorder):
            resolved = self.twilio_common._resolve_keepass_value(
                "Twilio/example-account#token",
                "password",
                "work",
            )

        self.assertEqual(resolved, "twilio-secret")
        self.assertEqual(recorder.load_calls[0].profile, "work")
        self.assertTrue(
            str(recorder.load_calls[0].path).endswith("auto-pass/config/auto-pass.env.local")
        )
        self.assertEqual(
            [call.entry for call in recorder.resolve_calls],
            ["Twilio/example-account#token", "twilio/example-account#token"],
        )
        self.assertEqual(recorder.resolve_calls[0].attrs_map, {"value": "password"})

    def test_gmail_keepass_non_lookup_error_becomes_config_error(self) -> None:
        recorder = AutoPassRecorder()
        recorder.add_response(
            "example-account#imap",
            recorder.keepass_error("database is locked"),
        )

        with AutoPassPatch(recorder):
            with self.assertRaises(self.gmail_common.ConfigError) as ctx:
                self.gmail_common._resolve_keepass_value(
                    "example-account#imap",
                    "password",
                    "infra",
                )

        message = str(ctx.exception)
        self.assertIn("KeePassXC resolution failed", message)
        self.assertIn("example-account#imap", message)
        self.assertIn("password", message)
        self.assertIn("infra", message)


if __name__ == "__main__":
    unittest.main()
