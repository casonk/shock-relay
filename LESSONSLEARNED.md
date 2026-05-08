# LESSONSLEARNED.md

Tracked durable lessons for `shock-relay`.
Unlike `CHATHISTORY.md`, this file should keep only reusable lessons that should change how future sessions work in this repo.

## How To Use

- Read this file after `AGENTS.md` and before `CHATHISTORY.md` when resuming work.
- Add lessons that generalize beyond a single session.
- Keep entries concise and action-oriented.
- Do not use this file for transient status updates or full session logs.

## Lessons

- Document the repository around its real execution, curation, or integration flow instead of only the top-level folder list.
- Keep local-only, private, reference-only, or generated boundaries explicit so published or runtime behavior is not confused with offline material or non-committable inputs.
- Re-run repo-appropriate validation after changing generated artifacts, diagrams, workflows, or other CI-facing files so formatting and compatibility issues are caught before push.

### 2026-03-26 — Keep shell wrappers shellcheck-clean under the CI gate

- The repository CI runs `shellcheck` on shell entrypoints, so quoting shortcuts and stale local variables will block pushes even when the scripts still execute locally.
- When adding or editing shell wrappers, validate them with `shellcheck`-compatible quoting patterns instead of relying on permissive local execution.

### 2026-03-27 — Multi-provider messaging repos need architecture grouped by adapter family

- Do not reduce the repo to a single `services/` box when the real implementation is several distinct adapter families.
- In `shock-relay`, the important split is direct `signal-cli` subprocess wrappers versus HTTP adapter families versus the IMAP/SMTP mail lane.
- Confirmation scripts such as `test_send_receive_confirm.*` are part of the implementation surface and should appear in architecture docs when they are the main integration harness.

### 2026-04-25 — Gmail IMAP label names with spaces must be mailbox-quoted for create/copy operations

- Gmail label application over IMAP is not just a `SELECT` problem; `CREATE` and `UID COPY` can also fail with `BAD Could not parse command` when the target label contains spaces.
- If a monitor applies a processed label after parsing mail, quote mailbox-style label names before attempting `CREATE`/`COPY` rather than assuming the helper's select-time quoting is enough.
- Apply the live label before saving the local dedupe state so a labeling failure stays retryable on the next run instead of being silently marked as already handled.

### 2026-04-25 — GitHub Actions failure emails must be parsed against the IMAP text shape, not only the Gmail/web rendering

- The same GitHub Actions failure notice can appear as a markdown-like table in Gmail's rendered body but as a flattened bullet summary in IMAP text, for example `* lint-and-test (3.11) failed (2 annotations)`.
- Inbox monitors should parse both body shapes and key their dedupe on the run URL / run id rather than on the exact body text layout.
- When validating an email parser, use a live inbox sample once before trusting an offline fixture built from a different rendering path.
