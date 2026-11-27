# Archipelago project commands. Run from the repo root.
# Each target skips parts of the stack that do not exist yet.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

HAS_BACKEND := $(wildcard backend/go.mod)
HAS_WEB     := $(wildcard web/package.json)
HAS_MOBILE  := $(wildcard mobile/pubspec.yaml)
HAS_INFRA   := $(wildcard infra/envs)

# Dev tools are pinned in tools/go.mod (golangci-lint in its own module, as its authors advise).
# Versions are verified by the Go checksum database and updated by Dependabot.
TOOLS_BIN   := $(CURDIR)/.tools/bin
TOOLS_STAMP := $(TOOLS_BIN)/.stamp
# Tools are called by full path ($(TOOLS_BIN)/x): GNU Make 3.81 (macOS) ignores PATH changes
# for its own command lookup. PATH is still exported for child processes (go generate).
export PATH := $(TOOLS_BIN):$(PATH)

.PHONY: help setup tools gen gen-check lint test test-int e2e security guard-test check

help: ## List commands
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

tools: $(TOOLS_STAMP) ## Install pinned dev tools into .tools/bin (needs Go)

$(TOOLS_STAMP): tools/go.mod tools/go.sum tools/golangci-lint/go.mod tools/golangci-lint/go.sum
	@command -v go >/dev/null || { echo "Go is needed for dev tools: brew install go"; exit 1; }
	GOBIN=$(TOOLS_BIN) go -C tools install tool
	GOBIN=$(TOOLS_BIN) go -C tools/golangci-lint install tool
	@touch $@

setup: tools ## Install tools and dependencies
ifneq ($(HAS_BACKEND),)
	cd backend && go mod download
endif
ifneq ($(HAS_WEB),)
	pnpm --dir web install --frozen-lockfile
endif
ifneq ($(HAS_MOBILE),)
	cd mobile && flutter pub get
endif

gen: tools ## Regenerate code from the API contract, SQL and design tokens
ifneq ($(HAS_BACKEND),)
	cd backend && go generate ./...
	cd backend && if [ -f sqlc.yaml ]; then $(TOOLS_BIN)/sqlc generate; fi
endif
ifneq ($(HAS_WEB),)
	pnpm --dir web run gen
endif
ifneq ($(HAS_MOBILE),)
	cd mobile && dart run build_runner build --delete-conflicting-outputs
endif

gen-check: ## Fail if 'make gen' changes anything (generated code out of date)
	@git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "gen-check needs a git repo (git init)"; exit 1; }
	@# GNU Make 3.81 (macOS) ignores .SHELLFLAGS, so multi-command recipes set strict mode themselves.
	@set -euo pipefail; \
	before=$$( (git diff; git ls-files --others --exclude-standard) | shasum ); \
	$(MAKE) --no-print-directory gen; \
	after=$$( (git diff; git ls-files --others --exclude-standard) | shasum ); \
	if [ "$$before" != "$$after" ]; then echo "Generated code was stale and has been regenerated: review and commit it."; exit 1; fi

lint: tools ## Format check, linters, type checks
ifneq ($(HAS_BACKEND),)
	cd backend && test -z "$$(gofmt -l .)" || (gofmt -l . && echo "Run gofmt" && exit 1)
	cd backend && $(TOOLS_BIN)/golangci-lint run ./...
endif
ifneq ($(HAS_WEB),)
	pnpm --dir web run lint
	pnpm --dir web run typecheck
endif
ifneq ($(HAS_MOBILE),)
	cd mobile && dart format --set-exit-if-changed lib test
	cd mobile && flutter analyze --fatal-infos
endif
ifneq ($(HAS_INFRA),)
	terraform fmt -check -recursive infra
endif

test: ## Unit tests (fast, no Docker)
ifneq ($(HAS_BACKEND),)
	cd backend && go test -race -count=1 ./...
endif
ifneq ($(HAS_WEB),)
	pnpm --dir web run test
endif
ifneq ($(HAS_MOBILE),)
	cd mobile && flutter test
endif

test-int: ## Integration tests (real PostgreSQL via Docker)
ifneq ($(HAS_BACKEND),)
	cd backend && go test -race -count=1 -tags=integration ./...
endif

e2e: ## Playwright end-to-end tests
ifneq ($(HAS_WEB),)
	pnpm --dir web exec playwright test
endif

guard-test: ## Test the Claude Code guard hook (policy SEN-SEC-POL-001)
	python3 .claude/hooks/test_guard.py

security: tools ## Secret scan and vulnerability scans
	@git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "security needs a git repo (git init)"; exit 1; }
	@# Scan what is or could be committed: history, uncommitted changes, and new files that are not
	@# gitignored. Ignored files (a developer's real .env) are skipped on purpose.
	$(TOOLS_BIN)/gitleaks git --no-banner --redact
	$(TOOLS_BIN)/gitleaks git --no-banner --redact --pre-commit
	$(TOOLS_BIN)/gitleaks git --no-banner --redact --pre-commit --staged
	set -euo pipefail; git ls-files -z --others --exclude-standard | \
	  xargs -0 -r -n1 $(TOOLS_BIN)/gitleaks dir --no-banner --redact --config $(CURDIR)/.gitleaks.toml
ifneq ($(HAS_BACKEND),)
	cd backend && $(TOOLS_BIN)/govulncheck ./...
endif
	@# Go call analysis is done by govulncheck above. Accepted tool vulns: tools/osv-scanner.toml.
	$(TOOLS_BIN)/osv-scanner scan source --recursive --allow-no-lockfiles --no-call-analysis=go .

check: gen-check lint test security guard-test ## Everything that must pass before "done"
	@echo "make check: all passed"
