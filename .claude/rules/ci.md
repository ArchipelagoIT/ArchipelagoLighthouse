---
paths:
  - ".github/**"
---
# CI/CD rules (GitHub Actions)

- Pin every third-party action to a full commit SHA with the version in a comment. Dependabot updates them.
- Minimal `permissions:` per job. AWS access only through GitHub OIDC roles, one per environment.
- PR pipeline: `make check`, then image build and Playwright against a preview or dev.
- Merge to `main` deploys to dev. Release tag (created by a human) builds once; the **same image** goes to staging, then prod after manual approval in a GitHub Environment.
- Branch protection on `main`: PR required, checks required, at least one human approval from someone who did not author it, no force push, signed commits. Tier 3 paths in `CODEOWNERS`.
- Tools used in CI come from `tools/go.mod` via `make tools` (versions verified by the Go checksum database). Never `curl` a binary or use `@latest`.
- Security scans. **In the template now:** gitleaks, govulncheck, osv-scanner (`make security`); gosec runs inside golangci-lint.
  **Add when the part exists** (and tick it off in `docs/project.md`):
  - `web/`: `pnpm audit --prod` in `make security`; Playwright + axe job.
  - Container images: Trivy (fail on fixable HIGH/CRITICAL).
  - `infra/`: checkov or tfsec.
  - Repo on GitHub: CodeQL (Go, JavaScript/TypeScript).
  - Staging deployed: weekly OWASP ZAP baseline against **staging** only.
- Never add a workflow step that writes to production without a human approval gate.
