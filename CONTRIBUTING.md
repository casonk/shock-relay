# Contributing

`shock-relay` is a multi-service messaging toolkit. Keep contributions scoped, configuration-safe, and consistent across services.

## Workflow

1. Make the smallest change that improves one service or one shared pattern.
2. Keep service-specific files inside the correct `services/<service>/` directory.
3. Update `README.md` and `AGENTS.md` when a command, config contract, or supported workflow changes.
4. Use Conventional Commits such as `feat(telegram): add receive offset flag` or `docs(gmail-imap): clarify smtp setup`.

## Security And Configuration

- Never commit `config.local.yaml` files, credentials, tokens, phone numbers, or email secrets.
- Keep example configs templated and environment-variable driven.
- Prefer `https://` endpoints for HTTP-backed services unless the repo explicitly documents a local-only development exception.

## Verification

- Run the narrowest useful smoke test for the service you changed.
- When adding a new service script, document the expected invocation in `README.md`.
- If the change affects shared conventions, verify the existing service directories still follow the documented config pattern.

## Pull Requests

- Keep each pull request limited to one service area or one shared refactor.
- Summarize config changes and any new environment variables.
- Note whether the change was validated with a live service, a dry run, or a static review only.
