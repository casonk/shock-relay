# Contributor Architecture Blueprint

This document is a concise map of how `shock-relay` implements messaging as
parallel provider adapters rather than a single top-level relay core.

## High-Level Layers

1. Service contract layer (`services/*/config.example.yaml`, local `config.local.yaml`)
   - Each provider owns its own tracked config template and local runtime config.
   - Secrets and account-specific values are typically resolved from environment
     variables referenced by the local config.
2. Signal subprocess lane (`services/signal-cli/*`)
   - The Signal scripts are intentionally lightweight and dependency-light.
   - Python and shell entrypoints extract a small amount of YAML and invoke the
     local `signal-cli` executable directly.
3. HTTP adapter family (`services/telegram`, `services/whatsapp`, `services/twilio`)
   - Each HTTP-backed provider keeps a `common.py` and `common.sh` beside the
     service entrypoints.
   - Those helpers own config parsing, env resolution, TLS validation, request
     helpers, response normalization, and allow-list enforcement.
   - Send/receive/test entrypoints layer on top of those helpers instead of
     talking to the remote APIs directly.
4. Mail protocol lane (`services/gmail-imap/*`)
   - `gmail-imap/common.py` owns IMAP settings, SMTP settings, TLS behavior,
     inbox filters, and mailbox normalization.
   - `check_inbox.py`, `send_email.py`, and `test_connection.py` are thin
     operator entrypoints over that common protocol layer.
5. Validation and documentation layer (`.github/workflows/ci.yml`, `docs/`)
   - CI validates Python syntax with `compileall` and shell entrypoints with
     `shellcheck`.
   - The architecture docs should reflect the adapter-family split and the fact
     that there is not yet a single top-level relay dispatcher.

## Key Entry Points

- `./services/signal-cli/send_message.py`
- `./services/telegram/send_message.py`
- `./services/whatsapp/send_message.py`
- `./services/twilio/send_sms.py`
- `./services/gmail-imap/test_connection.py`
- `./services/*/test_send_receive_confirm.py`
- `.github/workflows/ci.yml`

## Validation

```bash
python -m compileall services
find services -name '*.sh' -print0 | xargs -0 shellcheck
```

Because integrations depend on external services, CI stays limited to syntax and
static validation. Use the per-provider `test_send_receive_confirm.*` flows or
`gmail-imap/test_connection.py` only when the required local credentials and
remote accounts are available.
