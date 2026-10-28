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


class TelegramTokenFromVaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_module_by_path(
            REPO_ROOT / "services/telegram/common.py",
            module_name="shock_relay_telegram_common_test",
        )

    def _config(self, directory: Path, body: str) -> str:
        path = directory / "config.yaml"
        path.write_text(
            "service:\n  name: telegram\n"
            f"telegram:\n  api_base_url: https://api.telegram.org\n{body}",
            encoding="utf-8",
        )
        return str(path)

    def test_the_token_is_read_from_the_vault_entry_with_profile_and_field(self) -> None:
        import tempfile

        recorder = AutoPassRecorder()
        recorder.add_response("example/telegram-bot", {"value": "vault-token"})
        with tempfile.TemporaryDirectory() as tmp, AutoPassPatch(recorder):
            path = self._config(Path(tmp), "  bot_token_keepass_entry: example/telegram-bot\n")
            config = self.common.load_config(path)

        self.assertEqual(config.bot_token, "vault-token")
        self.assertEqual(recorder.load_calls[0].profile, "infra")
        self.assertEqual(recorder.resolve_calls[0].attrs_map, {"value": "password"})

    def test_a_literal_token_or_the_environment_variable_wins_over_the_vault(self) -> None:
        import os
        import tempfile
        from unittest import mock

        recorder = AutoPassRecorder()
        with tempfile.TemporaryDirectory() as tmp, AutoPassPatch(recorder):
            literal = self._config(
                Path(tmp),
                "  bot_token: literal-token\n  bot_token_keepass_entry: example/telegram-bot\n",
            )
            self.assertEqual(self.common.load_config(literal).bot_token, "literal-token")
            env_config = self._config(
                Path(tmp),
                "  bot_token_env: SYNTH_TG_TOKEN\n  bot_token_keepass_entry: example/telegram-bot\n",
            )
            with mock.patch.dict(os.environ, {"SYNTH_TG_TOKEN": "env-token"}):
                self.assertEqual(self.common.load_config(env_config).bot_token, "env-token")

        self.assertEqual(recorder.resolve_calls, [])

    def test_a_missing_vault_entry_is_a_clear_config_error(self) -> None:
        import tempfile

        recorder = AutoPassRecorder()
        recorder.add_response(
            "example/telegram-bot",
            recorder.keepass_error("Entry example/telegram-bot was not found."),
        )
        with tempfile.TemporaryDirectory() as tmp, AutoPassPatch(recorder):
            path = self._config(Path(tmp), "  bot_token_keepass_entry: example/telegram-bot\n")
            with self.assertRaisesRegex(self.common.ConfigError, "was not found"):
                self.common.load_config(path)

    def test_with_no_token_source_the_error_names_all_three(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(Path(tmp), "")
            with self.assertRaisesRegex(self.common.ConfigError, "bot_token_keepass_entry"):
                self.common.load_config(path)
