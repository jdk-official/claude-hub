# Decisions

Decisions made and why — the rationale behind the current shape. Durable
decisions also get their own record under `adr/` (see [adr/README.md](../adr/README.md)).

- 2026-10-13: Python stdlib + fzf stays; a rewrite only if startup is slow after caching.
- 2026-10-13: Vault is co-located in `docs/` (matches daily-hub; one clone, memory versioned with code).
- 2026-10-13: Gamification counts active days from authored commits, local clones only.
- 2026-10-13: Cache lives in `~/.cache/claude-hub/`, not on the data drive.
- 2026-10-13: Minimum Python 3.11; TOML config via `tomllib` (user-confirmed).
- 2026-10-13: Cache may hold PR/issue titles and counts, in `~/.cache/claude-hub/` (user-confirmed).
- 2026-10-13: Streak breaks only after a full empty calendar day (user-confirmed).
- 2026-10-13: Order is pinned, then needs-attention, then recency (user-confirmed).
- 2026-10-13: Weeks run Monday to Sunday; lines changed = insertions + deletions, merges excluded (user-confirmed).
- 2026-10-13: Keys: ctrl-r refresh, ctrl-l resume, ctrl-t tag filter; ctrl-g stays fzf's abort alias (user-confirmed).
- 2026-10-13: Search matches name and tags only (fields 2-3, `--with-nth 2,3,4 --nth 1,2`); verified by spike.
- 2026-10-13: Live refresh talks to fzf over a unix socket in a private 0700 per-session directory (XDG_RUNTIME_DIR, else
  the temp dir), removed on exit; never a TCP port. ctrl-r starts a detached refresh and returns at once.
- 2026-10-13: With --track, header updates are queued before reload (actions after reload are dropped).
- 2026-10-13: Auto-launch is a `~/.bashrc` block, not Ghostty `initial-command`: the latter only fires for the first surface of a
  fresh app start and never fires in the user's long-running single instance. Tabs and splits also open the picker; esc dismisses.
- 2026-10-13: PR/issue counts used for ordering come from the background refresh's bulk listing. Viewing a project may fetch PR
  titles for the preview but writes only prs.json, never the main cache, so it can neither reorder nor reload the list.
- 2026-10-13: claude-hub passes the same `--plugin-dir` for the project-dashboard mod that the user's `claude()` shell function adds.
- 2026-10-13: Project renamed claude-hub (repo, directory, titles). The command stays `claude-hub`, so the shell block, cache dir
  (~/.cache/claude-hub) and muscle memory are unchanged. GitHub keeps a redirect from the old repo name.
- 2026-10-13: Sessions are read from Claude Code's own registry and transcripts (no daemon of ours). Spares are hidden; a
  background session is "attached" when an interactive entry's parkedJobId equals its jobId.
- 2026-10-13: Stopping anything is explicit (ctrl-x) and confirmed; orphan SIGTERM requires registry pid and procStart to match.
- 2026-10-14: Worktrees are grouped under their parent and never de-duplicated against it (they share the remote).
- 2026-10-14: Statistics cannot exclude worktrees (one commit database); bulk commits (over 5000 lines) are reported apart.
- 2026-10-14: Print-mode and SDK sessions are `headless`, not `orphan`, so only abandoned interactive sessions are flagged.
- 2026-10-14: Tabs All/Local/GitHub/Other/Sessions on ctrl-s; Local and GitHub overlap; Sessions last, alt-5 jumps to it.
- 2026-10-14: Origin labels are gh:<owner>, dir:<name> or local; the folder name is never shown bare.
- 2026-10-14: An empty list is never passed to fzf (placeholder row), after an end-to-end test found stale rows and blocked input.
- 2026-10-14: Worktrees collapse under their parent by default; ctrl-w or show_worktrees expands them.
- 2026-10-14: ctrl-l resumes by session id, never `claude --continue` (it refuses when the latest conversation is
  running in the background and only guesses by directory).
- 2026-10-14: `claude agents --json --all` is the primary session source (documented); registry and transcripts enrich it.
- 2026-10-14: Auto-launch defaults to shells that start in the home directory; the claude() wrapper was removed.
