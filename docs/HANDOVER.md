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

- Done (2026-10-13): iteration 1 built autonomously and merged to main: tool checks, cache (`~/.cache/hub`),
  TOML config, scan roots, needs-attention ordering and markers, preview (commits, HANDOVER/README excerpt,
  PRs/issues), launch (new / resume with ctrl-l, clone confirm), stats header, per-repo sparkline,
  `hub stats` heatmap, responsive preview. 46 unit tests (`python3 -m unittest discover -s tests`).
- In progress: independent code review of iteration 1.
- Not done: iteration 2 (fzf header-first, footer, in-place reload, name-only search, tag filter).
- Unverified: behaviour in the real narrow Ghostty window; interactive launch into claude (tested up to
  the picker and preview only).

## How to resume

1. Read [INDEX.md](INDEX.md) to orient.
2. Read [ROUTER.md](ROUTER.md) and pick the lane for your task.
3. Read [tracking/ACTIVE.md](tracking/ACTIVE.md) for in-flight work.

## Open items

1. Triage the review findings, then push `main`.
2. Q1 fzf spike, then Q3-Q6 from [BACKLOG.md](tracking/BACKLOG.md).
3. Confirm the stats look right to the user (lines changed include vendored-tooling commits).
