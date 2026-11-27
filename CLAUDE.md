@AGENTS.md

## Claude Code specifics
- Use plan mode for any risk tier 3+ change.
- Run reviewers as subagents with a fresh context (see the `code-review` skill).
- At the end of a session, list what changed, which system was touched, and what is still unverified.
