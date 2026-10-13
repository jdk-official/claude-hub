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
  `hub stats` heatmap, responsive preview, dashboard (heatmap) on the home row. Tests: `python3 -m unittest discover -s tests`
  runs unit tests plus end-to-end tests that drive the real picker in tmux (needs tmux and fzf).
- Reviewed: independent code review (1 HIGH, 6 MEDIUM, 7 LOW) all addressed in `review-fixes`: failed refresh no longer
  wipes cached repos, clone cleanup can never delete a directory hub did not create, locked cache writes,
  git runs with fsmonitor/hooks disabled, stats union clones and flag timeouts. 63 tests.
- Reviewed twice (iteration 2 review: 1 HIGH, 4 MEDIUM, 6 LOW, all addressed or documented).
- Done (iteration 2): header above the prompt, key-hint footer, name-and-tags-only search, in-place background
  refresh over a private unix socket (`--listen`), `ctrl-r` refresh, `ctrl-t` tag filter. 22 end-to-end tests drive the
  real picker in tmux; the fzf spike script (tests/spikes/fzf_spike.py in the repo) verifies the fzf mechanisms (13/13).
- Unverified: behaviour in the real narrow Ghostty window; interactive launch into claude (tested up to
  the picker and preview only).

## How to resume

1. Read [INDEX.md](INDEX.md) to orient.
2. Read [ROUTER.md](ROUTER.md) and pick the lane for your task.
3. Read [tracking/ACTIVE.md](tracking/ACTIVE.md) for in-flight work.

## Open items

1. Verify the picker in the real narrow Ghostty window, then start iteration 2.
2. Iteration 3 (Ghostty auto-launch) from [BACKLOG.md](tracking/BACKLOG.md); fzf findings are in [fzf-spike](reference/fzf-spike.md).
3. Confirm the stats look right to the user (lines changed include vendored-tooling commits; line counts cover the last 14 days only, streaks and sparklines cover 400 days).
