---
updated: 2026-10-13
---

# hub — handover

## TL;DR

Terminal launcher: pick a recent repo (GitHub + local) and start claude in it, with git-stats gamification.

## Where things live

- Repo: `/mnt/data/github/hub`
- Vault: `/mnt/data/github/hub/docs`
- Index: [INDEX.md](INDEX.md) — the workspace map.
- Router: [ROUTER.md](ROUTER.md) — task → which notes to load.

## Current state

- Done: working launcher (`bin/hub`), requirements brainstorm with selected scope and gamification, repo on GitHub (`jdk-official/hub`, private), workspace scaffolded under agent-catalog.
- In progress: nothing implemented beyond v0.
- Blocked on the user: confirm the gamification counting rules and the open questions in section 4.

## How to resume

1. Read [INDEX.md](INDEX.md) to orient.
2. Read [ROUTER.md](ROUTER.md) and pick the lane for your task.
3. Read [tracking/ACTIVE.md](tracking/ACTIVE.md) for in-flight work.

## Open items

1. Cache + background refresh (M1/M2) and narrow-terminal layout (M5).
2. Header with streak and today/week stats (G1/G2); per-repo sparkline (G3).
3. Pin/hide config, tags, needs-attention sort, PRs/issues, HANDOVER excerpt, resume key.
