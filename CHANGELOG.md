# Changelog

All notable changes to `shock-relay` are documented here.

## Unreleased

- `deploy/deploy.sh` uses `set -eEuo pipefail` so an ERR trap also fires for failures inside functions (the deployment-modes contract), with a test.
- `deploy/k3s/verify.sh` waits for a previous verification pod to be fully gone before creating the next (its `sleep` ignored SIGTERM, so a second run within a minute exec'd into a terminating pod and reported false failures), and the verification pod now has a zero grace period.
- Deployment modes for the digest sender behind one setting: `deploy/deploy.sh [--mode dev|host|k3s] up|down|status|verify|mode`, with the mode from `--mode`, `SHOCK_RELAY_DEPLOY_MODE`, or `config/deploy.local.env` (example: `config/deploy.example.env`, gitignored), defaulting to `dev`. Only `k3s` touches kubectl, podman or a cluster. In K3s the sender is an hourly CronJob created suspended, with default-deny egress to Gmail SMTP and IMAP only, the Gmail credentials resolved from the vault on the host into a Secret (the pod config names environment variables and holds no credential), and the queue folder kept on the host. Hand-over happens only after `verify.sh` passes. `docs/deployment.md` explains each mode and how to switch.

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
