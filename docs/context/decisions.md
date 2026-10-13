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
