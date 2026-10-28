# Changelog

All notable changes to `shock-relay` are documented here.

## Unreleased

- Let the Telegram sender read its bot token from a KeePass entry through
  auto-pass (`telegram.bot_token_keepass_entry`), after a literal token and the
  environment variable, as the Gmail and Twilio senders already can. A missing
  entry is a clear configuration error.
- Add the `Private :: Do Not Upload` classifier so PyPI rejects an upload of this
  distribution; the repository is not published as a package.

- Added the portfolio-standard governance, continuity, and contributor baseline files.
