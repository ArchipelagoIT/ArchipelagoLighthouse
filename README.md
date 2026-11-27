# Archipelago Lighthouse

[One place to view every Archipelago hotel CCTV camera, live or recorded.]

## Start a new project from this template
1. Copy this folder, rename it, then `git init`.
2. Fill in `docs/project.md`.
3. In `.github/CODEOWNERS`, replace `@owner` with real GitHub users or teams.
4. Install Go (`brew install go`), then run `make setup`. This installs the pinned dev tools
   (gitleaks, osv-scanner, golangci-lint, sqlc, goose, ...) into `.tools/bin`.
5. Open Claude Code in the folder. Run `/sandbox` to confirm the sandbox is on, `/permissions` and
   `/hooks` to confirm the guard is active, and `make guard-test` to confirm it works.
   Use git over **HTTPS** (`gh auth setup-git`): git over SSH does not work inside the sandbox on macOS.
6. On GitHub, protect `main`: require a pull request, require review from Code Owners, block force
   pushes and deletions. This is what stops an agent from changing `main` or its own guard rails.
7. Ask Claude to run the **design-kickoff** skill before any UI work.
8. Create only the parts you need (Claude reads the matching `.claude/rules/` file first):
   - `backend/`: `go mod init <module>`
   - `web/`: `pnpm create next-app web --ts --app --eslint --tailwind`
   - `mobile/`: `flutter create --org com.archipelago mobile`
   Then uncomment the matching block in `.github/dependabot.yml`.
9. If the app needs local settings, create `.env` **yourself** in the project root and fill it in
   (it is gitignored, so it is never committed). Claude is blocked from reading or writing `.env`
   files, so list the setting names (never the values) in `docs/project.md`.
10. `make check`.

## Reviews
Tier 3+ changes get two independent reviewers: Opus (the `reviewer` subagent) and Codex.
Install the Codex CLI once per machine (see OpenAI's Codex docs), then run `codex login`.
Without Codex, Claude uses a second Opus reviewer and tells you.

Rules for the agent: `AGENTS.md` (core) and `.claude/rules/` (per folder).

## Guard rails
Three layers, each covering what the others cannot:

1. **Sandbox** (`sandbox` in `.claude/settings.json`), enforced by macOS for every shell command and
   every program it starts, except `git push` (see below). Shell tricks do not get past it.
   - No reads of `.env` and `.env.*` files (`.env.example` stays readable), key and signing files,
     `~/.ssh`, `~/.aws`, `~/.gnupg`, the gh, gcloud, 1Password, docker, kube, Terraform, Dart,
     Postgres, Gradle, PyPI and git credential files, `~/.claude.json`, shell history, or the keychain.
     `~/.npmrc` stays readable because npm needs it: keep tokens out of it where you can.
   - No writes to `.claude/`, `.mcp.json`, `.git/config`, `.git/hooks/`, `.git/commondir`,
     `.git/worktrees/`, `.git/modules/`. Outside the project, writes only to the temp folder and the
     shared caches (Go, golangci-lint, npm, the pnpm store, the pub cache), never to folders on your
     PATH or to the git repos Go and pub keep in their caches. The caches are shared with your own
     shell, so the agent could plant code in a cache that later **runs** in your terminal builds and
     `make test-int`. Nothing re-checks cache contents automatically (`go mod verify` checks the Go
     module cache when you run it).
   - Network only to the listed package and GitHub domains; for any other host Claude Code asks you.
     Add a domain there when a tool needs it. To refuse other hosts without asking, put
     `"sandbox": {"network": {"strictAllowlist": true}}` in your **user** settings
     (`~/.claude/settings.json`): Claude Code ignores that key in project settings. This is not
     airtight: an allowed domain such as `github.com` can receive uploads.
   - `allowUnsandboxedCommands: false`: the agent cannot ask to run outside the sandbox.
   - `enableWeakerNetworkIsolation: true` lets Go tools check TLS certificates on macOS (the trustd
     service); without it `govulncheck` and `go get` fail. Claude Code warns that it **reduces
     security**: it opens a possible path to send data out through trustd.
   - `excludedCommands: ["git push *"]`: `git push` runs **outside** the sandbox so it can use your
     GitHub login, and Claude Code asks you before every push. Claude Code runs the **whole** command
     unsandboxed if any one part of it matches (even `"git" push` or `noglob git push`), so the guard
     allows exactly one form, as its own command, from the project root:
     `git push [-u] origin <feat|fix|chore>/<name>`. The branch must exist locally and not also be a
     tag; `origin` must be an `https://github.com/...` URL; git must use the project's own `.git`
     (no worktree, nested or bare repo) with no `core.hooksPath` (husky, lefthook). Anything else,
     even a commit message that mentions "git push", is blocked: push those yourself or reword.
     `git push -u` writes the upstream branch into `.git/config`.
   - Everything else, including `git pull/fetch` and `gh`, stays inside the sandbox. `git pull/fetch`
     of public repos works. `gh` cannot run at all (it cannot read its login), so you open PRs
     yourself; the agent writes the PR text to a file and gives you the exact command.
   - The **Monitor** tool runs commands through the same sandbox check as Bash; the guard checks it
     the same way and asks you before it opens a WebSocket (which runs outside the sandbox).
   - `docker` does not work inside the sandbox. Read the diff (especially `Makefile`, `tools/` and
     test code) before you run `make test-int` yourself in a terminal: it runs with your full rights.
2. **Guard hook** (`.claude/hooks/guard.py`). Checks Claude's own Read, Edit, Write, WebFetch,
   Monitor and MCP tools, which the sandbox does not cover (the sandbox's read blocks apply to shell
   commands only), allows `git push` only in the one form above, and gives clear messages for shell
   commands (force push, production, secrets). Outside `git push` it is pattern matching: a
   seatbelt, not a lock.
3. **GitHub**: branch protection on `main` with Code Owner review. The sandbox cannot stop the agent
   from *committing* an older version of `.claude/` (git's staging area is writable); a human reviewing
   the PR does.

Limits to know:

- Environment variables are not protected by any layer. Keep production write credentials and
  GitHub tokens (`GH_TOKEN`, `GITHUB_TOKEN`) out of the shell you start Claude Code from.
  (`sandbox.credentials.envVars`, in user or managed settings, can hide named variables.)
- A person can turn these settings off with `.claude/settings.local.json` or `--settings`; the agent
  cannot. To lock them, IT can later push Claude Code **managed settings** to each Mac.
- Recommended in each developer's `~/.gitconfig`: `safe.bareRepository = explicit`.

`.claude/settings.json` and `.claude/hooks/` are changed by humans only. Test with `make guard-test`.
