---
paths:
  - "backend/db/**"
  - "backend/**/*.sql"
  - "backend/sqlc.yaml"
---
# PostgreSQL rules

- All SQL via `sqlc` (typed, parameterized). No string-built SQL, no ORM.
- Every query on a `hotel_id`-partitioned table filters on `hotel_id` (see AGENTS.md section 6).
- `snake_case`, plural tables, `id uuid primary key`, `created_at timestamptz not null default now()`, `updated_at timestamptz`.
- `timestamptz` for instants, `date` for business dates, `bigint` for money minor units.
- Foreign keys and `NOT NULL` by default. Index every foreign key and common filter; check with `EXPLAIN ANALYZE` on realistic generated data.
- Optimistic locking (`version` column) on records several people edit (reservations, room status).

## Migrations (risk tier 3)
- `goose` SQL files, one change each, never edited after merge.
- **Expand → migrate → contract.** Each migration must work with both the old and new app version running.
- No long locks: `CREATE INDEX CONCURRENTLY`, no volatile defaults on new columns, backfill in batches.
- Each migration has a tested rollback path (down migration or written restore plan).
- Run migrations only against your local or dev database. Production migrations run in CI after a human confirms a fresh RDS snapshot.
