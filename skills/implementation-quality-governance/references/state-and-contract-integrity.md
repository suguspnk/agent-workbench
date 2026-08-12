# State And Contract Integrity

For persistence, state transitions, concurrency, schema/migration, API/event, or compatibility work:

- Define mutation semantics: atomic or partial completion, retries, idempotency, ordering, duplicate handling, and user-visible errors. Identify contested-write invariants and enforce them with constraints, atomic conditional operations, transactions, isolation/locks, idempotency keys, deduplication, or an outbox—never check-then-write alone.
- Test concurrent, replayed, and reordered high-risk transitions where practical. Preserve compatibility surfaces and consumers; a breaking change needs explicit approval, versioning/migration, and mixed-version handling where relevant.
- For APIs/events, define and verify authentication, request/response fields, headers, nullability, precision, time zones, ordering, pagination, error/status semantics, rate limits, idempotency, partial success, async processing, cancellation, retriability, and affected consumers. Do not leak internals/private data.
- Preserve data unless destructive behavior is explicitly authorized. Plan schema changes as expand, migrate/backfill, switch, then contract where applicable. Define defaults, nullability, validation, constraints, tenant scope, uniqueness, indexes, ownership, and source-of-truth/read-write compatibility per rollout phase.
- Make backfills resumable and idempotent; handle existing records, partial failure, retries, reconciliation, transactions/checkpoints, runtime/locks/index constraints, replication/log volume, bloat, deadlocks, and connection pressure. Validate fresh setup, upgrade, and compatible rollback or forward-fix paths.
- For live data changes, define go/no-go and abort thresholds. For high-risk changes, define backup/restore expectations and verify them where supported; never claim rollback when prior semantics/data cannot actually be restored.
