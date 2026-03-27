# Contributor Architecture Blueprint

This document is a concise map of how `shock-relay` organizes per-service messaging adapters and shared operational patterns.

## High-Level Layers

1. Service-adapter layer (`services/*`)
   - Each service directory contains the service-specific entrypoints and config templates.
   - Current adapters include Signal, Telegram, WhatsApp, Twilio, and Gmail IMAP.
2. Python and shell entrypoint layer
   - Python scripts provide the main maintained automation surface.
   - Shell wrappers exist where a native shell interface is useful for quick automation.
3. Local configuration layer (`config.example.yaml` -> local `config.local.yaml`)
   - Each service documents its config contract in a tracked example file.
   - Real credentials remain local-only and are injected through env vars referenced by config.
4. Shared protocol/helper layer (`common.py`, `common.sh` where present)
   - Service directories can keep small shared helpers close to the integration that uses them.
   - Keep the adapters loosely coupled so new services can be added without a global refactor.

## Key Entry Points

- `./services/signal-cli/send_message.py`
- `./services/telegram/send_message.py`
- `./services/whatsapp/send_message.py`
- `./services/twilio/send_sms.py`
- `./services/gmail-imap/test_connection.py`
- `.github/workflows/ci.yml`

## Validation

```bash
python -m compileall services
find services -name '*.sh' -print0 | xargs -0 shellcheck
```

Because integrations depend on external services, keep CI limited to syntax and static validation unless a fully local test harness is added.
