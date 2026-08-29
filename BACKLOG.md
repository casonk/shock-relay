# BACKLOG.md

Portfolio backlog for this repository. Pending items are candidates for execution —
manually or via crew-chief. Entries sourced from archility audit are tagged
`[archility:YYYY-MM-DD]`; manual entries use `[manual:YYYY-MM-DD]`.

The archility twice-weekly job populates this file automatically via `archility audit --write-backlog`.
To execute a backlog item with crew-chief: `crew-chief agent "Work on item: <item text>"`.
Mark items `[x]` when complete and move them to Done.

## Pending

## In Progress

## Done

- [x] [manual:2026-08-29] **Migrate offline delivery queue to private-repository durable leases** — Replaced JSONL read/rewrite handling with leased SQLite commands, delayed retry/rejection outcomes, and idempotent legacy migration. Provider delivery remains explicitly at-least-once.
