---
updated: 2026-10-13
---

# claude-hub — handover

## TL;DR

Terminal launcher: pick a recent repo (GitHub + local) and start claude in it, with git-stats gamification.

## Where things live

- Repo: `/mnt/data/github/claude-hub`
- Vault: `/mnt/data/github/claude-hub/docs`
- Index: [INDEX.md](INDEX.md) — the workspace map.
- Router: [ROUTER.md](ROUTER.md) — task → which notes to load.

## Current state

- Done (2026-10-13): iteration 1 built autonomously and merged to main: tool checks, cache (`~/.cache/claude-hub`),
  TOML config, scan roots, needs-attention ordering and markers, preview (commits, HANDOVER/README excerpt,
  PRs/issues), launch (new / resume with ctrl-l, clone confirm), stats header, per-repo sparkline,
  `claude-hub stats` heatmap, responsive preview, dashboard (heatmap) on the home row. Tests: `python3 -m unittest discover -s tests`
  runs unit tests plus end-to-end tests that drive the real picker in tmux (needs tmux and fzf).
- Done (iteration 3): claude-hub opens in every new Ghostty shell via a `~/.bashrc` block (verified into the running instance);
  `initial-command` was dropped because it never fires in a long-running single instance. Opt out with CLAUDE_HUB_AUTOSTART=0.
- Fixed after use: viewing a project no longer moves it up (PR counts come from the refresh); claude-hub now launches claude
  with the dashboard mod like the shell function does.
- Done (after use): Sessions view (ctrl-s, `claude-hub sessions`): working, attached, detached, terminal,
  orphaned, stale and past sessions, with attach, resume and confirmed clean-up.
- Done (2026-10-14): session badges on project and home rows, worktrees grouped under parents, bulk lines
  reported separately, headless sessions distinguished from orphans, PRD brought up to date.
- Done (2026-10-14): source glyph on every row, honest origin labels, tabs on ctrl-s (All, Local, GitHub, Other,
  Sessions) with a counted tab bar, `start_tab` config, placeholder row for empty tabs.
- Done (2026-10-18): All, Local and GitHub merged into one Projects tab (Other and Sessions stay); Projects is ordered by
  last use (commit, push or Claude session) with attention shown as markers only. See adr/0001. 195 tests.
- Done (2026-10-18): summary rows lead the Sessions ("needs you") and Other ("stale", 90 days) tabs, each with a preview
  dashboard. 204 tests.
- Done (2026-10-14, UX review): worktrees collapsed, list-first layout, tab bar leads, ctrl-l by id, supported
  session listing, claude rm, help (alt-h), home-only auto-launch, stale wrapper removed.
- Reviewed: independent code review (1 HIGH, 6 MEDIUM, 7 LOW) all addressed in `review-fixes`: failed refresh no longer
  wipes cached repos, clone cleanup can never delete a directory claude-hub did not create, locked cache writes,
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
2. Watch how the Ghostty auto-launch behaves in daily use (see BACKLOG, iteration 3 notes); fzf findings are in [fzf-spike](reference/fzf-spike.md).
3. Confirm the stats look right to the user (lines changed include vendored-tooling commits; line counts cover the last 14 days only, streaks and sparklines cover 400 days).
