---
paths:
  - "backend/**/*.go"
  - "backend/go.mod"
  - "backend/go.sum"
---
# Go backend rules

## Stack
Latest stable Go; standard `net/http` routing; `log/slog` (JSON); `pgx/v5`; `sqlc`; `goose`; `oapi-codegen` for server interfaces; `testcontainers-go`; `golangci-lint` (with gosec, errcheck, staticcheck, revive); `govulncheck`.

## Structure
- `cmd/<service>/main.go`, `internal/<domain>/` with **handler → service → repository**. Handlers do HTTP only; repositories do SQL only; business rules live in services.
- `internal/platform/` for db, config, logging, auth middleware.
- Dependencies through constructors. No globals, no `init()` side effects.
- Config from env vars, validated at startup (fail fast). Secrets from AWS Secrets Manager at runtime.

## Code
- `context.Context` first; timeouts on every outgoing call and DB query; respect cancellation.
- Wrap errors with context (`fmt.Errorf("load reservation %s: %w", id, err)`); map domain errors to HTTP status in one place.
- No `panic` in request paths; recovery middleware returns 500 and logs.
- Logs include `request_id`, `hotel_id`, `user_id`.
- Inject a clock interface; never call `time.Now()` inside business logic.
- Goroutines need a clear owner, stop condition and error path. Concurrency changes are tier 3.
- HTTP server: `ReadHeaderTimeout`, `ReadTimeout`, `WriteTimeout`, `IdleTimeout`, body size limits, graceful shutdown on SIGTERM. `/healthz` and `/readyz`.

## Auth and security
- Proven libraries only (e.g. `go-webauthn`); never custom crypto or token formats.
- Staff/admin: SSO + passkeys (FIDO2), YubiKey recommended. Guests: passkey or email one-time code; SMS only as fallback. Passwords if ever needed: Argon2id + rate limit + breached-password check.
- Role-based access per hotel, checked in the service layer on every request.
- Sessions short-lived, rotated on login, revoked on logout and role change.
- Rate limits on login, OTP, search and booking. CORS to known origins only; CSRF protection on cookie-based writes.
- Uploads: check type and size, store in private S3, serve via signed URLs.

## Tests
- Table-driven unit tests for services, especially money, dates, availability and auth: **90 %+ line coverage** there; elsewhere coverage must not drop.
- Integration tests with `testcontainers-go` and real PostgreSQL for repositories, migrations and hotel isolation.
- Deterministic: fixed clock, fixed seeds, no real network, no sleeps.

## Observability
- Sentry with PII scrubbing; CloudWatch metrics and alarms for error rate, p95 latency, DB connections, payment and login failures.
- Each service has a runbook in `docs/runbooks/`.
