# Decisions

Decisions made and why — the rationale behind the current shape. Durable
decisions also get their own record under `adr/` (see [adr/README.md](../adr/README.md)).

- 2026-10-13: Python stdlib + fzf stays; a rewrite only if startup is slow after caching.
- 2026-10-13: Vault is co-located in `docs/` (matches daily-hub; one clone, memory versioned with code).
- 2026-10-13: Gamification counts active days from authored commits, local clones only.
- 2026-10-13: Cache lives in `~/.cache/hub/`, not on the data drive.
- 2026-10-13: Minimum Python 3.11; TOML config via `tomllib` (user-confirmed).
- 2026-10-13: Cache may hold PR/issue titles and counts, in `~/.cache/hub/` (user-confirmed).
- 2026-10-13: Streak breaks only after a full empty calendar day (user-confirmed).
- 2026-10-13: Order is pinned, then needs-attention, then recency (user-confirmed).
- 2026-10-13: Weeks run Monday to Sunday; lines changed = insertions + deletions, merges excluded (user-confirmed).
- 2026-10-13: Keys: ctrl-r refresh, ctrl-l resume, ctrl-t tag filter; ctrl-g stays fzf's abort alias (user-confirmed).
- 2026-10-13: Search matches name and tags only (fields 2-3, `--with-nth 2,3,4 --nth 1,2`); verified by spike.
- 2026-10-13: Live refresh talks to fzf over a unix socket in a private 0700 per-session directory (XDG_RUNTIME_DIR, else
  the temp dir), removed on exit; never a TCP port. ctrl-r starts a detached refresh and returns at once.
- 2026-10-13: With --track, header updates are queued before reload (actions after reload are dropped).
