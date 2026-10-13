# Backlog

Not-yet-started work, grouped. Promote an item to [ACTIVE.md](ACTIVE.md) when it starts.
Requirement IDs refer to the [PRD](../prd/hub.md). Status: iteration 1 built and merged to main on 2026-10-13 (P1-P11 plus Q2); iteration 2 not started.

## Done: iteration 1 (foundation, stats, content)

| ID | Item | Covers | Depends on |
|---|---|---|---|
| P1 | Missing-tool and Python-version checks, no tracebacks | FR-7, FR-8, AC-8 | none |
| P2 | Cache layer in `~/.cache/hub`, stale marker, corrupt recovery, offline fallback | FR-1, FR-4, FR-5, FR-6, AC-1, AC-7, AC-9 | P1 |
| P3 | TOML config: owners, scan roots, pinned, hidden, tags, count | FR-13, FR-14, AC-17, AC-18 | P2 |
| P4 | Scan roots, de-dup by remote URL, non-git directories | FR-9, FR-12, AC-23 | P3 |
| P5 | Needs-attention ordering and row markers | FR-16, FR-36, AC-20, AC-27 | P3 |
| P6 | Preview content: last 3 commits, HANDOVER/README excerpt, wrapping | FR-17, FR-18, FR-20, AC-24 | P2 |
| P7 | PR/issue counts and titles, lazy fetch and cache | FR-19 | P2, P6 |
| P8 | Launch: new vs resume (ctrl-l), clone confirm, clean abort, offline refusal | FR-23 to FR-27, AC-3 to AC-5, AC-21 | P1 |
| P9 | Stats engine: identity rules, active days, streak, today/week vs average | FR-28, FR-29, FR-32, FR-33, AC-10 to AC-12 | P4 |
| P10 | Per-repo 8-week sparkline | FR-30, AC-13, AC-14 | P9 |
| P11 | `hub stats` 12-week heatmap | FR-31, AC-15, AC-16 | P9 |

## Next: iteration 2 (remaining fzf-driven UI)

Starts with Q1, a spike on fzf 0.74.3 that settles PRD assumption row 11.

| ID | Item | Covers | Depends on |
|---|---|---|---|
| Q1 | Spike: verify --track, reload, become, --header-first, responsive preview | assumption row 11 | iteration 1 |
| Q2 | Responsive preview position (narrow: below, wide: beside). DONE in iteration 1 via the fzf `<100(down,40%)` alternative layout | FR-21, FR-22, AC-6 | none |
| Q3 | Stats header and key-hint footer | FR-35, AC-26 | Q1, P9 |
| Q4 | Full-list scrolling and name+tags-only search | FR-10, FR-11, FR-34, AC-19, AC-25 | Q1 |
| Q5 | In-place background refresh and ctrl-r | FR-2, FR-3, AC-2 | Q1, P2 |
| Q6 | Tag filter key (ctrl-t) | FR-15 | Q4, P3 |

Note: Q2 was pulled into iteration 1 (one preview-window flag). Not yet verified in the real narrow Ghostty window.

Iteration 1 also delivered: scrolling over the full list (up to 100 rows), part of FR-10/FR-11 (Q4); name+tags-only search (FR-34) and the tag filter are still open.

## Future: iteration 3 (desktop integration)

- Launch hub automatically when Ghostty starts. Candidate: `initial-command = bash -c 'hub; exec bash'` in the
  Ghostty config (first terminal only; falls back to a shell on esc). Open points: whether Ghostty runs as a
  single instance (later windows would not count as "first"), and whether to use `command` for every window.
  Requires the omarchy skill, a timestamped backup of the config, and `ghostty +validate-config`.
  Related existing items: Hyprland keybind (C5), login pre-warm (C6).

## Later

- Deferred gamification: ship counter, badges and milestones, weekly goal, finish-line nudge.
- Not selected: open-in-browser and plain-shell keys (S4), new scratch dir (C3), `--list --json` and `-q` (C4), Hyprland keybind (C5), login pre-warm (C6), per-repo `claude_args`.
- Adopt the backlog-delivery rails (bd-adopt, then pbi-plan) if the project outgrows this table.
