# Changelog

All notable changes to `shock-relay` are documented here.

## Unreleased

- Fix `send_digest.py --dry-run` deleting queued notifications: it popped the entries and never put them back,
  so a dry run lost them. It now only reports and leaves the queue untouched (it still honours `--limit`).
- Add `SHOCK_RELAY_DIGEST_IGNORE_ENTRY_CONFIG=1`: send every queued digest entry with the default `--config`
  instead of the host config path each entry recorded. A container cannot read those host paths, so without
  this every send failed and the entries were requeued. The default behaviour is unchanged.

- Let the Telegram sender read its bot token from a KeePass entry through
  auto-pass (`telegram.bot_token_keepass_entry`), after a literal token and the
  environment variable, as the Gmail and Twilio senders already can. A missing
  entry is a clear configuration error.
- Add the `Private :: Do Not Upload` classifier so PyPI rejects an upload of this
  distribution; the repository is not published as a package.

- Added the portfolio-standard governance, continuity, and contributor baseline files.
