# claude-hub

Terminal launcher (command: `claude-hub`, repo: `jdk-official/claude-hub`): lists recent repos (GitHub + local), previews their state, and launches
`claude` in the one you pick. Runs in Ghostty (`ghostty -e claude-hub`).

- Script: `bin/claude-hub` (Python 3 + fzf + gh + git), symlinked to `~/.local/bin/claude-hub`
- Requirements brainstorm: `docs/requirements-brainstorm.md`
- Workspace vault: [docs/INDEX.md](docs/INDEX.md) (handover, router, ADRs, tracking)
- Tabs: `ctrl-s` cycles Projects, Other and Sessions (`alt-s` back, `alt-1`..`alt-3` jump). Projects is everything that is
  yours, local or on GitHub, newest use first (latest commit, push or Claude session). Other is plain folders and other people's clones. A leading glyph
  says where each row lives: `◆` local and GitHub, `⌂` local only, `◌` GitHub only, `◇` someone else's clone,
  `▫` plain folder, `↳` worktree. `claude-hub sessions` prints the session list as text. Session glyphs: `▶` working, `◉` attached, `○` detached,
  `▣` in a terminal, `◈` headless, `⚠` orphaned, `✗` stale, `·` past (shown as a key on the Sessions tab).
- Keys: `ctrl-l` continue the last session in a project (by id), `ctrl-w` show/hide worktrees (collapsed by
  default), `ctrl-r` refresh, `ctrl-t` tags, `ctrl-x` stop/clean up a session (asks first), `alt-h` help.
- Config (`~/.config/claude-hub/config`, TOML, optional): `start_tab = "other"` picks the tab it opens on (`projects` by default; old `all`/`local`/`github` mean `projects`);
  `show_worktrees = true` lists worktrees by default; also `owners`, `scan_roots`, `pinned`, `hidden`, `count`
  and a `[tags]` table (keys must come before the table).
- Auto-launch: a block in `~/.bashrc` starts claude-hub when a new Ghostty shell starts in your home directory.
  `CLAUDE_HUB_AUTOSTART=always` shows it in every new Ghostty shell; `CLAUDE_HUB_AUTOSTART=0` turns it off.
