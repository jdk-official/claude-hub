# Conventions

House style and patterns to follow when changing this codebase.

- Follow the governance rules in `/mnt/data/github/agent-catalog/plugins/governance/rules/`.
- Stdlib-only Python, no pip dependencies; hub never runs destructive git operations.
- Secrets and caches stay in `~`; nothing sensitive is written to the data drive.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. No force-push on `main`.
