# Security Policy

## Reporting

Do not file sensitive disclosures in public issues.

For `shock-relay`, security-sensitive reports should be handled privately by the repository owner.

When reporting an issue, redact any local environment details that are not required to understand the problem.

## Scope

- Do not commit credentials, tokens, private keys, or machine-specific local configuration.
- Do not commit unnecessary absolute filesystem paths, usernames, hostnames, or other local-environment identifiers.
- Treat `CHATHISTORY.md` as local-only operational memory and do not publish it.
- Never commit live service tokens, phone numbers, inbox credentials, or any `config.local.yaml` file.

## Transport Security

- Keep TLS verification enabled in normal operation. The service examples set
  `*.tls.insecure_skip_verify: false` by default, and that should remain the
  steady-state configuration.
- Treat `imap.tls.insecure_skip_verify`, `smtp.tls.insecure_skip_verify`,
  `telegram.tls.insecure_skip_verify`, `twilio.tls.insecure_skip_verify`, and
  `http.tls.insecure_skip_verify` as break-glass settings for short-lived local
  debugging against a trusted endpoint only.
- When a private CA or self-signed certificate is involved, prefer
  `ca_cert_path` or `ca_cert_path_env` over disabling verification.
- Do not run message delivery, inbox polling, or credentialed health checks
  over unverified TLS on an untrusted network. Those flows carry live tokens,
  phone numbers, inbox credentials, or message contents.

## Safe Documentation Practices

- Prefer relative paths and location-neutral wording in committed docs when they are operationally sufficient.
- Keep durable workflow guidance in tracked docs such as `AGENTS.md`, `README.md`, and architecture docs.
- Keep transient handoff notes in the local-only repo-root `CHATHISTORY.md` file.
