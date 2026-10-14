# Backlog

Not-yet-started work, grouped. Promote an item to [ACTIVE.md](ACTIVE.md) when it starts.
Requirement IDs refer to the [PRD](../prd/claude-hub.md). Status: iteration 1 (P1-P11 plus Q2) and iteration 2 (Q1, Q3-Q6) built on 2026-10-13.

## Done: iteration 1 (foundation, stats, content)

| ID | Item | Covers | Depends on |
|---|---|---|---|
| P1 | Missing-tool and Python-version checks, no tracebacks | FR-7, FR-8, AC-8 | none |
| P2 | Cache layer in `~/.cache/claude-hub`, stale marker, corrupt recovery, offline fallback | FR-1, FR-4, FR-5, FR-6, AC-1, AC-7, AC-9 | P1 |
| P3 | TOML config: owners, scan roots, pinned, hidden, tags, count | FR-13, FR-14, AC-17, AC-18 | P2 |
| P4 | Scan roots, de-dup by remote URL, non-git directories | FR-9, FR-12, AC-23 | P3 |
| P5 | Needs-attention ordering and row markers | FR-16, FR-36, AC-20, AC-27 | P3 |
| P6 | Preview content: last 3 commits, HANDOVER/README excerpt, wrapping | FR-17, FR-18, FR-20, AC-24 | P2 |
| P7 | PR/issue counts and titles, lazy fetch and cache | FR-19 | P2, P6 |
| P8 | Launch: new vs resume (ctrl-l), clone confirm, clean abort, offline refusal | FR-23 to FR-27, AC-3 to AC-5, AC-21 | P1 |
| P9 | Stats engine: identity rules, active days, streak, today/week vs average | FR-28, FR-29, FR-32, FR-33, AC-10 to AC-12 | P4 |
| P10 | Per-repo 8-week sparkline | FR-30, AC-13, AC-14 | P9 |
| P11 | `claude-hub stats` 12-week heatmap | FR-31, AC-15, AC-16 | P9 |

## Done: iteration 2 (fzf-driven UI), built 2026-10-13

All of Q1 to Q6 are done; see the covered requirement IDs below.

| ID | Item | Covers | Depends on |
|---|---|---|---|
| Q1 | DONE 2026-10-13: spike verified --track, reload, become, --header-first, --footer, --nth (11/11); see [fzf-spike](../reference/fzf-spike.md) | assumption row 11 | iteration 1 |
| Q2 | Responsive preview position (narrow: below, wide: beside). DONE in iteration 1 via the fzf `<100(down,40%)` alternative layout | FR-21, FR-22, AC-6 | none |
| Q3 | DONE: Stats header and key-hint footer | FR-35, AC-26 | Q1, P9 |
| Q4 | DONE: Full-list scrolling and name+tags-only search | FR-10, FR-11, FR-34, AC-19, AC-25 | Q1 |
| Q5 | DONE: In-place background refresh and ctrl-r | FR-2, FR-3, AC-2 | Q1, P2 |
| Q6 | DONE: Tag filter key (ctrl-t) | FR-15 | Q4, P3 |

Note: Q2 was pulled into iteration 1 (one preview-window flag). Not yet verified in the real narrow Ghostty window.

Iteration 1 also delivered: scrolling over the full list (up to 100 rows), part of FR-10/FR-11 (Q4); name+tags-only search (FR-34) and the tag filter are still open.

## Done: iteration 3 (desktop integration), built 2026-10-13

- Auto-launch moved from Ghostty `initial-command` to a small block at the end of `~/.bashrc`. Reason: with a
  background single-instance Ghostty (`--initial-window=false`, quick terminal, a Codex window) `initial-command`
  only fires for the first surface when the app starts, so `ghostty` did nothing. The shell block runs for every
  new interactive Ghostty shell, so it fires for windows opened into the running instance.
- The block: runs `claude-hub` when `TERM_PROGRAM=ghostty`, `CLAUDE_HUB_STARTED` is unset and `CLAUDE_HUB_AUTOSTART` is not `0`; it
  exports `CLAUDE_HUB_STARTED` so nested shells skip it. Esc leaves you at the prompt in the same shell, so Ghostty's
  shell integration is kept.
- Verified: `ghostty +new-window` into the running instance opened claude-hub; closing that window left the instance and
  other windows alone. Commands run with `-e` (codex, claude keybind, btop) bypass the shell and are unaffected.
- Behaviour to know: new tabs and splits are new shells, so they also open the picker; esc dismisses it. Disable
  everywhere with `CLAUDE_HUB_AUTOSTART=0` (add `export CLAUDE_HUB_AUTOSTART=0` to the shell, or delete the block).
- To revert: remove the block from `~/.bashrc` (backups: `~/.bashrc.bak-<timestamp>`).

## Done: sessions view, built 2026-10-13

Prompted by: "this is very project focussed; what if I have open sessions, or orphaned claude sessions".

- `ctrl-s` switches between Projects and Sessions; the header always carries a one-line summary
  (`sessions: 1 working · 2 attached · 2 in terminals · 14 resumable`). `claude-hub sessions` prints the same
  list as plain text (useful over remote control).
- Data: the live registry in `~/.claude/sessions/*.json` plus transcripts in `~/.claude/projects/*/*.jsonl`.
  Pre-warmed `spare` sessions and blank transcripts are hidden. `procStart` is compared with `/proc` start time
  so a reused pid is never mistaken for a live session.
- States: working, attached (a background session parked in a terminal), detached (background, nobody viewing),
  terminal (interactive, in a terminal), orphan (interactive, terminal gone), stale (registry entry, process
  gone), past (resumable transcript).
- Enter: background sessions run `claude attach <job>`; past sessions run `claude --resume <id>` in their
  directory (home if it no longer exists); terminal sessions explain where they are.
- `ctrl-x` (always asks first): stops a background session (`claude stop`), SIGTERMs an orphaned process only
  when pid and registry agree, or removes a stale registry entry. Nothing else is ever touched.
- Not done: focusing the window that holds a terminal session; showing sessions as a badge on project rows.

## Done: badges, worktrees and bulk lines, built 2026-10-14

- Session badges: a running-session count on each project row and on the home row, display only (never reorders).
  Found and fixed on real data: a `claude -p` run was shown as an orphan; it is now `headless`.
- Worktrees are listed beneath their parent (indented, `⎇N` on the parent), are not de-duplicated against it, and
  make the parent "needs attention" when dirty. The preview lists a project's other worktrees and live sessions.
- Bulk lines: commits above 5000 changed lines count as commits but their lines are reported as "(+55k bulk)".
  Excluding worktrees from statistics was investigated and rejected: all checkouts share one commit database.
- PRD brought up to date (FR-37 to FR-48, AC-28 to AC-38).

## Done: source tabs, built 2026-10-14

Prompted by: "make it clearer whether something is in GitHub, local or other".

- Leading source glyph on every row (`◆ ⌂ ◌ ◇ ▫ ↳`); the old trailing `◌` marker was removed as redundant.
- Honest origin labels: `gh:<owner>`, `dir:<name>`, `local`. The bare `github` that meant the folder is gone.
- Tabs on `ctrl-s` (All, Local, GitHub, Other, Sessions), `alt-s` back, `alt-1`..`alt-5` jump, counts in a tab bar.
- `start_tab` configuration key, default `all`.
- Empty tabs show a placeholder row (an fzf `--track` finding; see the fzf reference).
- Polish found by looking at the real window: `☁` and `⎘` rendered two cells wide, so GitHub-only is now `◌` and
  someone else's clone is `◇` (all glyphs single-width); the state text is capped so it cannot push the origin off
  screen; the origin column sits before the state; long worktree names drop their parent's prefix; on a tab where
  every row has the same origin the column is dropped.
- Session glyph key (asked for after use): two short header lines on the Sessions tab, also on the dashboard
  and at the end of `claude-hub sessions`; session rows now lead with their state glyph so it survives a narrow
  pane; headless uses a single-width glyph (`◈`) because `⚙` rendered double-width.
- Not done from the brainstorm: colour by source, section dividers, a per-row footer ("enter: clone" vs "open").

## Done: UX review round, built 2026-10-14

Prompted by "review the user experience" plus a source-backed check of how Claude's resume and background
sessions behave.

- Worktrees collapsed under their parent (`⎇N`, header note, `ctrl-w`, `show_worktrees`); stops two projects
  from taking most of the list.
- List-first layout: preview 38% beside the list, stacked below until ~121 columns, so the origin is visible.
- Header: tab bar first. The stats line was removed from the left pane afterwards (it duplicated the home
  dashboard, which is selected on opening); streak, today and week appear once, on the dashboard.
- Ages in minutes and hours; wrong "see next launch" copy fixed; `alt-h` help with both glyph keys.
- `ctrl-l` resumes a specific session by id (never `--continue`, which refuses when the latest conversation is
  running in the background); the preview names the target.
- Sessions read from `claude agents --json --all` (documented), registry as enrichment; `claude rm` for idle
  background sessions.
- Auto-launch only when a shell starts in the home directory (`CLAUDE_HUB_AUTOSTART=always|0` to change).
- Stale `claude()` wrapper removed from `~/.bashrc` (its mod directory no longer exists; the feature is a plugin).
- Not done: colour by source, per-row footer, abbreviating the header further for ~50-column windows.

## Later

- Deferred gamification: ship counter, badges and milestones, weekly goal, finish-line nudge.
- Not selected: open-in-browser and plain-shell keys (S4), new scratch dir (C3), `--list --json` and `-q` (C4), Hyprland keybind (C5), login pre-warm (C6), per-repo `claude_args`.
- Verify the layout in the real narrow Ghostty window; shorten very long worktree names in the list.
- Adopt the backlog-delivery rails (bd-adopt, then pbi-plan) if the project outgrows this table.
