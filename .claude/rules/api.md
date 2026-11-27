---
paths:
  - "api/**"
---
# API contract rules

- Change `api/openapi.yaml` **before** handler or client code; then `make gen`. CI fails if generated code is stale.
- REST + JSON, `camelCase` fields, plural nouns: `/v1/hotels/{hotelId}/reservations`.
- Version in the path (`/v1`). Breaking changes need a new version or a deprecation period. Changing a wire format or saved ID is risk tier 3.
- IDs: UUIDv7 strings. Never expose sequential database IDs.
- Money: `{ "amountMinor": 150000000, "currency": "IDR" }`. Business dates `YYYY-MM-DD`; timestamps RFC 3339 with offset.
- Errors: RFC 9457 Problem Details (`type`, `title`, `status`, `detail`, `instance`) plus a machine `code`. No stack traces or SQL in responses.
- Pagination: cursor-based, `?cursor=&limit=`, max limit 100.
- Retryable writes (bookings, payments) accept an `Idempotency-Key` header.
- Every endpoint declares its auth requirement and which hotel scope it needs.
