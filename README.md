# claude-hub

Terminal launcher (command: `claude-hub`, repo: `jdk-official/claude-hub`): lists recent repos (GitHub + local), previews their state, and launches
`claude` in the one you pick. Runs in Ghostty (`ghostty -e claude-hub`).

- Script: `bin/claude-hub` (Python 3 + fzf + gh + git), symlinked to `~/.local/bin/claude-hub`
- Requirements brainstorm: `docs/requirements-brainstorm.md`
- Workspace vault: [docs/INDEX.md](docs/INDEX.md) (handover, router, ADRs, tracking)
- Tabs: `ctrl-s` cycles All, Local, GitHub, Other and Sessions (`alt-s` back, `alt-1`..`alt-5` jump). A leading glyph
  says where each row lives: `◆` local and GitHub, `⌂` local only, `◌` GitHub only, `◇` someone else's clone,
  `▫` plain folder, `↳` worktree. `claude-hub sessions` prints the session list as text. Session glyphs: `▶` working, `◉` attached, `○` detached,
  `▣` in a terminal, `◈` headless, `⚠` orphaned, `✗` stale, `·` past (shown as a key on the Sessions tab).
- Config (`~/.config/claude-hub/config`, TOML, optional): `start_tab = "local"` picks the tab it opens on;
  also `owners`, `scan_roots`, `pinned`, `hidden`, `count` and a `[tags]` table (keys must come before the table).
