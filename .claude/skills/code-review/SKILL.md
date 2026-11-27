---
name: code-review
description: Review committed code at the right risk tier, or get independent opinions on a hard decision. Use before opening a PR, when the user asks for a review, after any change touching auth/secrets, money, migrations, wire formats, concurrency or date/time boundaries, and for architecture, schema or security decisions.
---

# Code review

## 1. Pick the tier (AGENTS.md section 8)
- Tier 1 (mechanical): self-check the diff, run `make check`, done.
- Tier 2 (normal): one fresh Opus reviewer, effort **low**.
- Tier 3 (silent or hard to undo): Opus **and** Codex in parallel, effort **medium**.
- Tier 4 (several tier-3 areas, or reviewers disagree): both, effort **high**.
- Tier 5 (still stuck): strongest model available (Fable or Astra), diagnosis or review only.
Set effort explicitly; use the same effort for both reviewers. Tell the user which tier and why.

## 2. Prepare
- Commit the change first. Reviewers review **committed** code.
- Write one neutral brief and give it **unchanged** to each reviewer:
  - what changed and why (from the ticket, not your opinion),
  - the requirements,
  - the files or commit range,
  - "Find problems or prove this code wrong. Report each finding with file, line, why it is wrong, and how to confirm it."
- Do **not** include your own conclusion or say the code is correct.

## 3. Run
Start both reviewers at the same time with the same brief.
- **Opus:** the `reviewer` subagent (`.claude/agents/reviewer.md`), which has a fresh context and is read-only.
- **Codex:** only reviews and advises; it never writes code. Run it in a read-only sandbox
  from the repo root (save the brief to a scratch file first):
  ```bash
  codex exec --sandbox read-only --ephemeral \
    -c model_reasoning_effort=<low|medium|high> \
    "$(cat <brief-file>)"
  ```
  Use the same effort as the Opus reviewer. Never use `--dangerously-bypass-approvals-and-sandbox`
  or a writable sandbox. If `codex` is missing or not logged in (`codex login status`),
  use a second `reviewer` subagent instead and **tell the user the second-model check was skipped**.

## 4. Act on findings
- Verify each finding yourself (reproduce, read the code, run a test) before changing anything.
- Bug fixes need a test that fails on the old code and passes on the new. Run both and show output.
- If reviewers disagree, weigh both and record the reasoning in a code comment or the PR.
- Report to the user: findings, what you verified, what you changed, what you rejected and why.

## Hard decisions (architecture, schema, security, hard to undo)
1. Write one neutral question with the context and options, without your preference.
2. Ask Opus and Codex in parallel (same fallback rule as above).
3. Show both answers and your recommendation. **A person decides.**
4. Record the decision as an ADR in `docs/decisions/NNNN-title.md`.
