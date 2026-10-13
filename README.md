# claude-hub

Terminal launcher (command: `claude-hub`, repo: `jdk-official/claude-hub`): lists recent repos (GitHub + local), previews their state, and launches
`claude` in the one you pick. Runs in Ghostty (`ghostty -e claude-hub`).

- Script: `bin/claude-hub` (Python 3 + fzf + gh + git), symlinked to `~/.local/bin/claude-hub`
- Requirements brainstorm: `docs/requirements-brainstorm.md`
- Workspace vault: [docs/INDEX.md](docs/INDEX.md) (handover, router, ADRs, tracking)
- Sessions: `ctrl-s` in the picker, or `claude-hub sessions` for a text list (open, background, orphaned, past)
