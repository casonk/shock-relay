# LESSONSLEARNED.md

Tracked durable lessons for `shock-relay`.
Unlike `CHATHISTORY.md`, this file should keep only reusable lessons that should change how future sessions work in this repo.

## How To Use

- Read this file after `AGENTS.md` and before `CHATHISTORY.md` when resuming work.
- Add lessons that generalize beyond a single session.
- Keep entries concise and action-oriented.
- Do not use this file for transient status updates or full session logs.

## Lessons

### 2026-03-26 — Keep shell wrappers shellcheck-clean under the CI gate

- The repository CI runs `shellcheck` on shell entrypoints, so quoting shortcuts and stale local variables will block pushes even when the scripts still execute locally.
- When adding or editing shell wrappers, validate them with `shellcheck`-compatible quoting patterns instead of relying on permissive local execution.

### 2026-03-27 — Multi-provider messaging repos need architecture grouped by adapter family

- Do not reduce the repo to a single `services/` box when the real implementation is several distinct adapter families.
- In `shock-relay`, the important split is direct `signal-cli` subprocess wrappers versus HTTP adapter families versus the IMAP/SMTP mail lane.
- Confirmation scripts such as `test_send_receive_confirm.*` are part of the implementation surface and should appear in architecture docs when they are the main integration harness.
