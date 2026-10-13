# Decisions

Decisions made and why — the rationale behind the current shape. Durable
decisions also get their own record under `adr/` (see [adr/README.md](../adr/README.md)).

- 2026-10-13: Python stdlib + fzf stays; a rewrite only if startup is slow after caching.
- 2026-10-13: Vault is co-located in `docs/` (matches daily-hub; one clone, memory versioned with code).
- 2026-10-13: Gamification counts active days from authored commits, local clones only.
- 2026-10-13: Cache lives in `~/.cache/hub/`, not on the data drive.
