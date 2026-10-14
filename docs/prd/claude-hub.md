# claude-hub: product requirements

Status: authored from `requirements-brainstorm.md` (primary), `bin/claude-hub` (v0, ~165 lines), the repo README, `HANDOVER.md`, `context/*.md`. Nothing here is implemented or tested. All timings are targets, not measurements.

Glossary: **scan root** = a directory whose immediate subdirectories claude-hub lists as projects. **Active day** = a calendar day with at least one qualifying commit. **Qualifying commit** = a commit that passes the counting rules in section 8 (rows 1-8).

## 1. Intended outcomes

- The user opens a narrow tiled Ghostty window, sees recent projects immediately, and is inside `claude` in the right directory within a second or two, without typing `cd` or `gh repo clone`.
- Every project the user owns locally or on GitHub is reachable by typing a few characters, not only the 10 most recent.
- Projects that need attention (dirty, unpushed, open PR) are visible at the top without inspecting each one.
- Steady building is made visible: the header shows streak and today/week activity, each repo shows an 8-week sparkline, and `claude-hub stats` shows a 12-week heatmap, all computed offline.
- Work that is already running is visible and reachable: open, background, orphaned and past Claude sessions are listed, badged on their project, and can be attached, resumed or cleaned up from the same picker.
- Worktrees do not clutter the list or the numbers: they sit under their parent project, and bulk imports do not drown real activity in the line counts.
- The picker is where every new Ghostty terminal starts, and looking at a project never changes what the list shows.
- claude-hub remains a safe launcher: it never changes repository history or state, and it only stops a Claude session after an explicit, confirmed request.

## 2. Scope - in / out

**In**
- Cached list with background refresh (M1, M2, S8).
- Fuzzy search over the full cached list (up to 100 repos).
- Pinned and hidden repos via config (S6).
- Extra scan roots `/mnt/data/files` and `/mnt/data/scratch` (C2, promoted).
- Tags and groups with a picker filter key (T1).
- "Needs attention" ordering (A1).
- Open PRs and issues in the preview (C1, promoted).
- HANDOVER / README excerpt in the preview (S1).
- Resume vs new session (S3).
- Narrow-terminal layout, graceful degradation, clone confirmation (M3-M8, S2).
- Gamification G1 (streak), G2 (today/week vs 4-week average), G3 (8-week sparkline), G8 (`claude-hub stats` 12-week heatmap).
- Sessions view (added 2026-10-13): `ctrl-s` toggle, session classification, attach/resume, confirmed clean-up, `claude-hub sessions` text list, session badges on project and home rows.
- Worktrees grouped under their parent project; bulk-commit lines reported separately.
- Auto-launch in new Ghostty shells via a shell-profile block (opt out with CLAUDE_HUB_AUTOSTART=0).
- Project, command, repo, cache and configuration names are `claude-hub` (renamed 2026-10-13).

**Out**
- Gamification deferred: ship counter, badges and milestones, weekly goal, finish-line nudge.
- Not selected: `ctrl-o` open-in-browser and plain-shell actions (S4), new-scratch-dir action (C3), `--list --json` and `-q` (C4), Hyprland keybind (C5), login pre-warm (C6), per-repo `claude_args` (open question 12).
- Non-goals: file manager, project/task tracker, git client (no commit, push, pull, rebase, branch switch, PR creation), multi-user/server/daemon, Claude transcript viewer or editor (the Sessions view lists, attaches, resumes and cleans up sessions but never edits them), GUI or TUI framework beyond fzf, mouse UI, secrets/token/SSH/`gh` auth management, non-GitHub forges, Windows/macOS, background auto-clone/pull/delete, editing Hyprland/Ghostty configs.

## 3. Decisions already made

| # | Decision | Source |
|---|----------|--------|
| D-1 | Python stdlib + fzf stays; a rewrite only if startup is slow after caching. | `context/decisions.md`, 2026-10-13 entry 1; also stated by the user in session |
| D-2 | The cache lives in `~/.cache/claude-hub/`, not on the data drive. | `context/decisions.md`, 2026-10-13 entry 4; also stated by the user in session |
| D-3 | Gamification counts active days from authored commits, local clones only. | `context/decisions.md`, 2026-10-13 entry 3 |
| D-4 | The selected scope in section 2 (features and G1/G2/G3/G8) was chosen by the user. | `requirements-brainstorm.md` section 4b, "chosen by the user, 2026-10-13" |
| D-5 | Minimum Python 3.11; config is TOML via stdlib `tomllib` (resolves assumption row 12). | Confirmed by the user, 2026-10-13 |
| D-6 | The cache may hold PR/issue counts and titles, not only counts (resolves row 19). | Confirmed by the user, 2026-10-13 |
| D-7 | A streak survives until a full calendar day passes with no qualifying commit (resolves row 8). | Confirmed by the user, 2026-10-13 |
| D-8 | Needs-attention repos (dirty, unpushed, open PR) outrank newer clean repos; pinned first (resolves row 13). | Confirmed by the user, 2026-10-13 |
| D-9 | Weeks run Monday to Sunday; "this week" is week-to-date (resolves row 6). | Confirmed by the user, 2026-10-13 |
| D-10 | Lines changed = insertions plus deletions from numstat, merge commits excluded (resolves row 7). | Confirmed by the user, 2026-10-13 |
| D-12 | Sessions are read from Claude Code's own registry and transcripts; pre-warmed spare sessions and transcripts with no user message are hidden; a process is only trusted when its registry start time matches the real one. | Built and verified against the user's live sessions, 2026-10-13 |
| D-13 | Session badges and worktree grouping are display only and never change ordering; viewing a project writes no cache that affects order or triggers a reload. | User report "viewing a project bumps it up", 2026-10-13 |
| D-14 | Auto-launch is a shell-profile block, not Ghostty `initial-command`, because `initial-command` never fires in a long-running single-instance Ghostty. | Verified, 2026-10-13 |
| D-15 | A single commit above 5000 changed lines is a bulk import: it counts as a commit but its lines are reported separately. Worktrees cannot be excluded from statistics because they share one commit database. | Measured on `daily-hub`: 57 identical commits from every checkout; one 54,814-line commit of 74,960 lines, 2026-10-13 |
| D-16 | The command and project are named `claude-hub`; environment variables are `CLAUDE_HUB_*`. | User request, 2026-10-13 |
| D-17 | Tabs: All, Local, GitHub, Other, Sessions. Local (your git repos on this machine) and GitHub (your repos on GitHub, cloned or not) overlap on purpose; Other is plain folders and others' clones; Sessions is the last tab and `alt-5` reaches it directly. | User brief, "where does this live" brainstorm, 2026-10-14 |
| D-18 | An empty list is never given to fzf: under `--track` an empty reload leaves the previous tab's rows on screen and, on the Sessions tab, blocks input. | Found by end-to-end tests and verified, 2026-10-14 |
| D-11 | Keys: `ctrl-r` refresh, `ctrl-l` resume (`claude --continue`), `ctrl-t` tag filter; `ctrl-g` is left as fzf's abort alias; `ctrl-l` overrides fzf's clear-screen (fzf 0.74.3). | Confirmed by the user, 2026-10-13 |

## 4. Functional requirements

Cache, refresh, degradation
- **FR-1** When claude-hub starts, the launcher shall render the picker from the cache in `~/.cache/claude-hub/` without waiting for any GitHub call.
- **FR-2** While the picker is open, the launcher shall refresh GitHub data and local git state in the background and update the list in place when results arrive.
- **FR-3** When the user presses `ctrl-r`, the launcher shall start the GitHub fetch and statistics refresh in the background without blocking input, and redraw the list when it finishes.
- **FR-4** If the cache is missing, corrupt, or unreadable, then the launcher shall ignore it and rebuild it without exiting.
- **FR-5** If the cache is older than 24 hours, then the launcher shall mark it as stale in the header.
- **FR-6** If `gh` is missing, unauthenticated, offline, or times out, then the launcher shall list local repos and state in one header line that GitHub is unavailable.
- **FR-7** If `fzf`, `claude`, or `git` is missing, then the launcher shall exit non-zero with a one-line message naming the missing tool and how to install it.
- **FR-8** If the Python version is below the minimum in section 6 (C-8), then the launcher shall exit non-zero with a one-line message.

Listing, search, organisation
- **FR-9** Where scan roots are configured (default `/mnt/data/github`, `/mnt/data/files`, `/mnt/data/scratch`), the launcher shall list each immediate subdirectory of each root, aged by last commit time for git repos and by directory mtime otherwise.
- **FR-10** When the user types a query, the launcher shall fuzzy-match it against all cached repos (up to 100), not only those visible.
- **FR-34** The launcher shall match the query against repo name and tags only, not against age, branch, markers or sparkline text.
- **FR-11** While the query is empty, the launcher shall list all cached repos in the FR-16 order, so that the first 10 rows (configurable `count`, the initial visible window) are the highest-ranked and the rest are reachable by scrolling.
- **FR-12** The launcher shall label each row with its origin (GitHub owner or scan-root directory) and de-duplicate repos by remote URL rather than by name.
- **FR-13** Where a repo is listed as hidden in `~/.config/claude-hub/config`, the launcher shall omit it from the list.
- **FR-14** Where a repo is listed as pinned in `~/.config/claude-hub/config`, the launcher shall sort it ahead of all unpinned repos.
- **FR-15** When the user presses the tag-filter key, the launcher shall restrict the list to repos carrying the selected tag from `~/.config/claude-hub/config`.
- **FR-16** When the list is built or refreshed, the launcher shall order pinned repos first, then repos that (or whose worktrees) are dirty, have unpushed commits, or have an open PR, then the remainder by most recent activity (latest of last commit and last push).

Preview
- **FR-17** When a repo is highlighted, the launcher shall show its last 3 commits as subject and age in the preview.
- **FR-18** When a repo is highlighted, the launcher shall show the first 10 lines of its HANDOVER.md, or of its README when no HANDOVER.md exists, read live from disk.
- **FR-19** The launcher shall take open PR and issue counts from the background GitHub listing (so ordering is stable from the first frame), and when a repo is highlighted shall show the titles of the top 3, fetched lazily and cached separately from the list.
- **FR-20** When the preview renders, the launcher shall word-wrap description and paths to the pane width without clipping.
- **FR-21** While the terminal is 60 columns wide or narrower, the launcher shall show each row on one line with the repo name intact and place the preview below the list.
- **FR-22** While the terminal is 100 columns wide or wider, the launcher shall place the preview beside the list.
- **FR-35** The launcher shall show the streak and today/week statistics in a header above the prompt, and a one-line key hint footer (Enter new, `ctrl-l` resume, `ctrl-r` refresh, `ctrl-t` tag, `esc` quit).
- **FR-36** The launcher shall mark each row with: pinned, dirty-file count, commits ahead of upstream, open PR count, GitHub-only (not cloned), as shown in section 4a.

Launch
- **FR-23** When the user presses Enter on a locally present repo, the launcher shall change to the repo directory and exec `claude` as a new session.
- **FR-24** When the user presses `ctrl-l` on a locally present repo, the launcher shall change to the repo directory and exec `claude --continue`.
- **FR-25** When the user selects a GitHub-only repo, the launcher shall ask for y/N confirmation before cloning into `/mnt/data/github/<name>`.
- **FR-26** If the user answers anything other than "y" or the clone fails, then the launcher shall abort leaving no partial directory.
- **FR-27** If the user selects a GitHub-only repo while GitHub is unreachable, then the launcher shall refuse the clone with a clear message.

Gamification
- **FR-28** When the header renders, the launcher shall show the current streak and the best streak in active days.
- **FR-29** When the header renders, the launcher shall show today's and this week's active repos, commits, and lines changed against the user's own 4-week average.
- **FR-30** When a repo is highlighted, the launcher shall show a sparkline of commits per week for the last 8 weeks in the preview.
- **FR-31** When the user runs `claude-hub stats`, the launcher shall print a 12-week contribution heatmap to the terminal.
- **FR-32** The launcher shall compute all statistics from local git history and make no network call for them.
- **FR-33** The launcher shall count each calendar day with at least one qualifying commit once toward streaks and averages, regardless of the number of commits that day.

Sessions, worktrees and statistics (added 2026-10-13)
- **FR-37** (superseded by FR-51) When the user presses `ctrl-s`, the launcher shall switch the list, prompt and header and keep the picker open.
- **FR-38** The launcher shall classify each Claude session as working, attached, detached, terminal, headless, orphan, stale or past from the registry and transcripts, hiding pre-warmed spare sessions and transcripts that contain no user message.
- **FR-39** The launcher shall treat a registry entry as running only when its recorded process start time equals the live process's start time, so a reused process id is never reported as a session.
- **FR-40** When Enter is pressed on a background session, the launcher shall run `claude attach`; on a past session, `claude --resume` in its recorded directory (the home directory with a notice if it no longer exists); on terminal, headless, orphan and stale sessions it shall explain and not launch.
- **FR-41** When `ctrl-x` is pressed on a session, the launcher shall ask for confirmation before stopping a background session, signalling an orphan whose process id and start time match the registry, or removing a stale registry entry, and shall touch nothing else.
- **FR-42** The launcher shall show a one-line sessions summary in the header, and a running-session count on each project row (and the home row) for sessions whose directory is inside it, without changing the list order.
- **FR-43** The command `claude-hub sessions` shall print the session list and summary as plain text.
- **FR-44** The launcher shall list a linked git worktree directly beneath its parent project marked with an indent, show a worktree count on the parent, not de-duplicate a worktree against its parent, and let a parent inherit its worktrees' recency and needs-attention state.
- **FR-45** The launcher shall count a commit whose changed lines exceed 5000 as a commit but report its lines separately as bulk lines.
- **FR-46** Highlighting a project shall not change the list order and shall not trigger a list reload.
- **FR-47** When a new interactive shell starts inside Ghostty and `CLAUDE_HUB_AUTOSTART` is not `0` and `CLAUDE_HUB_STARTED` is unset, the shell profile shall run `claude-hub` once; Esc shall leave the user at the shell.
- **FR-49** The launcher shall begin every project row with a source glyph: `◆` on this machine and on GitHub, `⌂` local only, `◌` on GitHub but not cloned, `◇` someone else's clone, `▫` plain folder, `↳` linked worktree.
- **FR-50** The launcher shall label each row's origin as `gh:<owner>` for a GitHub remote, `dir:<name>` for a scan root other than the clone root, and `local` for the clone root without a GitHub remote, and shall never show a bare folder name that reads as a hosting service.
- **FR-51** The launcher shall offer the tabs All, Local, GitHub, Other and Sessions; `ctrl-s` shall move to the next tab, `alt-s` to the previous, and `alt-1` to `alt-5` shall jump to a tab; moving past either end shall wrap.
- **FR-52** The header shall show a tab bar with a count per tab and the current tab marked.
- **FR-53** The launcher shall open on the tab named by the `start_tab` configuration key (default `all`), or on Sessions when started with `--sessions`.
- **FR-54** The launcher shall never give fzf an empty list; an empty tab shall show one inert placeholder row that Enter, `ctrl-l` and `ctrl-x` ignore.
- **FR-55** While the Sessions tab is shown, the header shall carry a key to the session glyphs (working, attached, detached, terminal, headless, orphan, stale, past) in lines short enough for a 50-column terminal, each session row shall begin with its state glyph, and the key shall also appear on the home dashboard and at the end of `claude-hub sessions`.
- **FR-56** The launcher shall show linked worktrees collapsed under their parent project by default, with a count on the parent and a header note of how many are collapsed; `ctrl-w` and the `show_worktrees` setting shall expand them.
- **FR-57** The header shall lead with the tab bar, followed by a GitHub status line only when something needs attention (loading, unavailable, stale or `gh` not installed); it shall not repeat the statistics (streak, today, week, bulk lines), which are shown once, on the home dashboard that is selected when the picker opens.
- **FR-58** The list shall have layout priority: the side-by-side preview shall take no more than 38% of the width and shall be stacked below the list when the terminal is narrower than about 121 columns.
- **FR-59** Ages shall resolve to minutes and hours inside a day (`12m ago`, `3h ago`).
- **FR-60** The launcher shall provide a help view (`alt-h`) listing the keys, the project glyphs, the markers and the session glyphs.
- **FR-61** `ctrl-l` shall continue the most recent resumable session of the project by its session id (attaching if it is a running background session) and shall start a new session when there is none; it shall not use `claude --continue`. The project preview shall name the session `ctrl-l` will use.
- **FR-62** The launcher shall read sessions from `claude agents --json --all` (the supported listing) in addition to the registry, shall work from the supported listing alone if the registry changes shape, and shall prefer its display name.
- **FR-63** `ctrl-x` shall remove an idle background session from the list with `claude rm` (transcript kept) and stop a working one with `claude stop`, each after confirmation.
- **FR-64** The shell-profile auto-launch (FR-47) shall by default run only when the shell starts in the home directory; `CLAUDE_HUB_AUTOSTART=always` shall run it in every new Ghostty shell and `0` shall disable it.
- **FR-48** (superseded 2026-10-14) The launcher added the project-dashboard mod flag; that feature is now an enabled plugin, so no flag is added.

## 4a. Interface layout (mock-up reviewed and accepted by the user, 2026-10-13)

Illustrative data, not measurements. Narrow window (about 50 columns, preview below the list):

```
 claude-hub  streak 12d (best 31)  today 3c · 2 repos · +184/-61
 week 19c · 5 repos · +1.2k/-0.4k   (avg 14c)   cache 2m
 ───────────────────────────────────────────────────
 > ho                                    12/48
 ───────────────────────────────────────────────────
 ★ claude-hub              ●3 ↑2   main    today   ▂▅█▃▁▁▂▆
 ★ daily-hub        ●1      main    today   ▁▁▃▅▂▁▁▁
   agent-catalog    ↑1 PR2  main    2d      ▃▁▁▂▁▁▄▁
   PSDRoster  ◌     PR1     —       today   ▁▁▁▁▂▅▃█
   SADashboard              main    7d      ▁▁▁▁▁▂▁▁
 ───────────────────────────────────────────────────
 claude-hub  jdk-official · private · local+gh · #tools
 last: a2086f7 Fix vault-relative paths in PRD  1h
       fb0f076 Record remaining PRD decisions   5m
 PRs 0 · issues 0
 HANDOVER: Terminal launcher: pick a recent repo...
 ───────────────────────────────────────────────────
 ⏎ new  ^l resume  ^r refresh  ^t tag  esc quit
```

Wide window (100 columns or more): same content with the preview pane to the right of the list.

Markers: `★` pinned, `●N` dirty files, `↑N` commits ahead, `PRN` open PRs, `◌` GitHub-only (not cloned), `—` no branch. Sparkline is the last 8 weeks of commits. `claude-hub stats` prints a separate 12-week heatmap of at most 80 columns (FR-31, NFR-6).

Implementation notes (design, not requirements): fzf provides the preview position switching, header and footer, match count, `reload` with `--track`, and `become` for launch. Name and tags are the searchable fields; the other columns are display-only.

## 5. Non-functional requirements

All numbers are targets to be measured, not measurements.

- **NFR-1** Picker visible within 300 ms of launch with a warm cache (target).
- **NFR-2** Picker visible within 1 s of launch with a cold cache, local repos only (target).
- **NFR-3** GitHub fetch timeout of 20 s; the fetch never blocks keyboard input.
- **NFR-4** Per-repo git call timeout of 3 s (proposed; v0 uses 15 s); a repo exceeding it is skipped for that refresh.
- **NFR-5** Rows and header lines render without wrapping or clipping at 50 columns; layout designed for a ~384 px tiled window (45-55 columns, unverified).
- **NFR-6** `claude-hub stats` output is at most 80 columns wide.
- **NFR-7** The cache contains no tokens or credentials; only repo metadata, PR/issue titles and counts, and aggregate commit statistics.
- **NFR-8** Building the session list reads the registry and a bounded number of transcript heads (40 past sessions) and never scans whole transcripts, so a multi-megabyte transcript does not slow the picker.

## 6. Constraints

- **C-1** Single-file Python using the standard library only, plus `fzf`, `gh`, `git`, `claude`; no pip dependencies (D-1).
- **C-2** The cache is written only under `~/.cache/claude-hub/` (D-2).
- **C-3** claude-hub performs no destructive or state-changing git operation: no push, reset, clean, force, commit, pull, rebase, or branch switch. Clone is the only write operation and always asks first.
- **C-4** claude-hub never writes credentials, tokens, or `gh` output beyond repo metadata outside `~`; the config file holds non-secret values only.
- **C-5** Statistics use local clones only and no network (D-3).
- **C-6** Primary layout target is a narrow tiled Ghostty window; GitHub only; Linux only (user session; non-goals).
- **C-7** Clone target is always `/mnt/data/github/<name>`.
- **C-8** Minimum Python 3.11 (assumed, row 12).
- **C-9** Stopping anything is limited to the explicit confirmed actions in FR-41; claude-hub never kills or deletes a session on its own initiative.

## 7. Acceptance criteria

- **AC-1** When `gh` is replaced by a command that sleeps 30 s, the picker shall be visible and accept input within 1 s.
- **AC-2** When a repo is pushed from another machine and one refresh completes, the picker shall show or re-sort that repo without a restart.
- **AC-3** When Enter is pressed on a local repo, `claude` shall start with a working directory equal to the repo path and the claude-hub process shall no longer exist.
- **AC-4** When "n" is answered at the clone prompt, the launcher shall leave nothing on disk at the clone target.
- **AC-5** If the clone command is forced to fail, then the launcher shall exit non-zero and leave no partial directory.
- **AC-6** While the terminal is 50 columns wide, each row shall fit on one line with the name intact and the preview shall appear below the list.
- **AC-7** If `PATH` lacks `gh`, then the picker shall open with local repos and the header shall state that GitHub is unavailable.
- **AC-8** If `PATH` lacks `fzf` or `claude`, then claude-hub shall print one line naming the tool and exit non-zero without a traceback.
- **AC-9** When the cached GitHub fetch time is more than 24 h old (edit `gh.fetched_at` in the cache file), the header shall show "STALE". A failed refresh shall not reset that fetch time or discard the cached repos.
- **AC-10** When a qualifying commit is made today in any scanned repo and a refresh completes, the current streak shall increase by one for that day only.
- **AC-11** If a full calendar day passes with no qualifying commit, then the current streak shall read 0.
- **AC-12** When a refresh completes, the today and this-week figures shall equal the sums of `git log --author` over the scanned repos for the same period.
- **AC-13** When a repo has no commits in the last 8 weeks, its sparkline shall render flat.
- **AC-14** When a repo has commits in exactly one of the last 8 weeks, its sparkline shall show one tall bar.
- **AC-15** When `claude-hub stats` runs, each heatmap cell shall match that day's qualifying-commit count.
- **AC-16** When `claude-hub stats` runs, no output line shall exceed 80 columns.
- **AC-17** Where a repo is hidden in config, it shall be absent from the list and from search results.
- **AC-18** Where a repo is pinned in config, it shall sort above all unpinned repos.
- **AC-19** While the query is non-empty, a repo ranked beyond the first 10 shall be selectable by typing part of its name.
- **AC-20** If a repo is dirty and unpinned, then it shall be ranked above a clean unpinned repo with newer activity.
- **AC-21** When `ctrl-l` is pressed on a repo with a prior session, claude-hub shall exec `claude --continue` in that directory.
- **AC-22** The claude-hub source shall contain no invocation of `git push`, `reset`, `clean`, or a forced operation.
- **AC-23** Given a scratch directory without `.git` under `/mnt/data/scratch`, when claude-hub lists projects, then the directory is listed, aged by mtime, and launchable.
- **AC-24** Given one repo with a HANDOVER.md and one with only a README, when each is highlighted, then the preview shows the HANDOVER.md lines for the first and the README lines for the second.
- **AC-25** When the query is `main`, no repo shall match solely because its branch is `main`.
- **AC-26** While the picker is open, the key hint footer shall list the Enter, `ctrl-l`, `ctrl-r`, `ctrl-t` and `esc` actions.
- **AC-27** Given a repo that is dirty, ahead of upstream, has an open PR, or is GitHub-only, when the list renders, then the row shows the matching marker from section 4a.
- **AC-28** Given background, terminal, headless, orphan, stale and past sessions in the registry and transcripts, when `ctrl-s` is pressed, then each row shows its state and the header summary counts them.
- **AC-29** Given a registry entry whose recorded start time differs from the live process, when sessions are classified, then it is stale, not running.
- **AC-30** Given a spare (pre-warmed) session and a transcript with no user message, when sessions are listed, then neither appears.
- **AC-31** When Enter is pressed on a background session, `claude attach <id>` shall be run; on a past session, `claude --resume <id>` shall be run in its directory.
- **AC-32** When `ctrl-x` is pressed on a stale entry and the user answers anything other than "y", the registry file shall still exist; after "y" it shall be removed.
- **AC-33** Given a print-mode (`claude -p`) session with no terminal, when sessions are classified, then it is headless and not orphaned.
- **AC-34** Given a session whose directory is inside a project, when the list renders, then that project's row shows its count, and the order is identical with and without the session.
- **AC-35** Given a project with a linked worktree that shares its remote, when the list renders, then both are listed, the worktree directly beneath its parent, and Enter on the worktree launches `claude` in the worktree directory.
- **AC-36** Given a commit of more than 5000 changed lines, when statistics are computed, then the day's commit count includes it and its lines appear in the bulk figure, not the ordinary lines.
- **AC-37** When every project is highlighted in turn, the list order shall be unchanged.
- **AC-38** Given a new Ghostty window opened into a running Ghostty, when its shell starts, then the picker is shown.
- **AC-39** Given a synced repo, a GitHub-only repo, a local-only repo, a folder and someone else's clone, when the list renders, then each row begins with `◆`, `◌`, `⌂`, `▫` and `◇` respectively.
- **AC-40** Given a repo with no GitHub remote under the clone root and a folder under another scan root, when the list renders, then their origins read `local` and `dir:<name>`, and no row's origin is the bare word `github` unless it is a GitHub owner prefixed `gh:`.
- **AC-41** When `ctrl-s` is pressed five times from All, the tabs shall be Local, GitHub, Other, Sessions and All, and each shall list only its own rows; a synced repo shall appear under both Local and GitHub.
- **AC-42** When `alt-s` is pressed on All, the Sessions tab shall be shown; when `alt-3` is pressed, the GitHub tab shall be shown.
- **AC-43** Given `start_tab = "github"` in the configuration, when the picker opens, then the GitHub tab is shown.
- **AC-44** Given a tab with no rows, when it is selected, then a placeholder row is shown, no rows from the previous tab remain, and the next tab key still works.
- **AC-45** Given the Sessions tab, when it is shown, then the header lists all eight glyphs with their names, every legend line is at most 44 characters, and each session row begins with the glyph of its state.
- **AC-46** Given a project with worktrees, when the list renders with default settings, then the worktrees are not listed, the parent shows `⎇N`, the header says how many are collapsed, and `ctrl-w` lists them.
- **AC-47** When the picker opens, the first header line is the tab bar and no header line repeats the streak or week figures.
- **AC-48** Given a terminal 130 columns wide, when the list renders beside the preview, then each row's origin label is fully visible.
- **AC-49** Given a project with a past session, when `ctrl-l` is pressed, then `claude --resume <that session id>` is run in the project; given no sessions, a new session is started; `--continue` is never used.
- **AC-50** Given the sessions listing returns a session the registry does not contain, then it appears on the Sessions tab.
- **AC-51** Given an idle background session, when `ctrl-x` is confirmed, then `claude rm <id>` is run; for a working one, `claude stop <id>`.
- **AC-52** Given a shell that starts in a project directory, when auto-launch is evaluated with default settings, then the picker is not shown; given the home directory, it is.

## 8. Assumptions & open questions

| # | Gap | Default chosen | Impact if wrong |
|---|-----|----------------|-----------------|
| 1 | Author identities for counting (brainstorm: "to confirm"). Exact GitHub noreply form unknown. | Match author email `jonathan@kyte.me.uk` or any `*@users.noreply.github.com` address containing `jdk-official`. | Streak and averages undercount or include foreign commits; adjust identity list. |
| 2 | How bots are detected. | Exclude authors whose name or email contains `[bot]`. | Bot commits inflate stats, or a legitimate author is dropped. |
| 3 | Commits with a `Co-Authored-By: Claude` trailer (brainstorm: counts, "to confirm"). | They count; a commit matching the identity or carrying the trailer is qualifying. | Streaks shrink if the user later wants only hand-written commits. |
| 4 | Counting rules are marked "to confirm" in the brainstorm, while `context/decisions.md` records active days and local-only as decided (D-3). | Treat D-3 as decided; G2 displays raw commit counts, while streaks and averages use active days (FR-33). | If raw commits should drive the average, FR-29/FR-33 change. |
| 5 | Which clones are in stats. | All git repos under all scan roots (including those with no GitHub remote); GitHub-only repos excluded. | Stats omit work in repos outside scan roots. |
| 6 | Time basis for days and weeks. | Author date in local timezone; week runs Monday-Sunday; "this week" is week-to-date; 4-week average is the mean of the 4 preceding complete weeks. | Day/week boundaries shift; ACs 10-15 need restating. |
| 7 | Which commits and what "lines changed" means. | `git log --all` per repo, deduplicated by hash within a repo, merges excluded; lines changed = insertions plus deletions from numstat. | Counts differ from `git log --author` checks in AC-12. |
| 8 | Whether today without a commit breaks the current streak. | Streak stays alive until the day ends; it resets only after a full day without a qualifying commit (AC-11). | Header shows 0 each morning if the opposite is wanted. |
| 9 | Owners and collaborator/org repos (open question 3). | Only `jdk-official`; config key `owners` reserved for more. | Org or collaborator repos are missing from the list. |
| 10 | Enter vs resume (open question 2); `ctrl-l` key confirmed by the user (fzf binds it to clear-screen by default; claude-hub overrides it); `claude --continue` behaviour per directory is unverified. | Enter starts new, `ctrl-l` resumes; revisit if resume exceeds 70% of launches. | Wrong default costs a keystroke per launch; key may clash with fzf bindings. |
| 11 | Feasibility, unverified: whether fzf (installed version unknown) supports showing 10 rows until typed while searching all 100, in-place list updates from a background refresh (reload/listen), and `change-preview-window` toggling, from a stdlib Python wrapper. | VERIFIED 2026-10-13 on fzf 0.74.3 (see reference/fzf-spike.md): `--listen` + `reload` with `--track --id-nth`, `change-header`, `--header-first`, `--footer`, `become`, and `--with-nth 1,2 --nth 1` for name-only search all work. Original assumption: feasible with `--bind` reload/change actions (with `--track`) and `become` for launch; the list is shown in full and scrolls (FR-11), so no "10 rows until typed" mechanism is needed. Fallback is a reload only on `ctrl-r`. Cost of the mechanism is unstated. | FR-2, FR-10, FR-11, FR-21/22 may need rework or a weaker behaviour; startup NFRs may be missed. |
| 12 | Config format and the minimum Python version. TOML via stdlib `tomllib` requires 3.11, conflicting with the brainstorm's 3.8 floor. | `~/.config/claude-hub/config` is TOML; minimum Python 3.11 (C-8); keys: owners, scan_roots, pinned, hidden, tags, count. | If 3.8 support is required, switch to `configparser` and restate FR-8/C-8. |
| 13 | Needs-attention definition and data. PR counts exist only after a lazy fetch (FR-19). | Tiers: pinned, then needs-attention (dirty, ahead of upstream, or cached open PR), then recency; a repo with no cached PR data is not boosted by PRs. | Attention ordering under-reports PR-only repos until first highlighted. |
| 14 | Tag syntax and filter key (T1). | Tags are a per-repo list in config; filter key `ctrl-t` opens a tag chooser; untagged repos have no tag. | Key or shape must change; group semantics (nested groups) unsupported. |
| 15 | HANDOVER location and excerpt length (S1 says "first ~10 lines"). | Look for `HANDOVER.md` at repo root, then the `docs/` folder, else the repo README; 10 lines. | Repos such as this one (docs/HANDOVER.md) show the wrong excerpt. |
| 16 | How extra scan roots are enumerated (C2). | Each immediate subdirectory is a project; non-git directories aged by mtime; clones still go only to `/mnt/data/github`. | Noise from non-project folders in `/mnt/data/files`; hide via config. |
| 17 | Layout between 61 and 99 columns; exact column count of the ~384 px window is unverified; floating window (open question 7) deferred. | Preview below the list for 61-99 columns; tiled narrow window remains the target; verify with `tput cols`. | NFR-5 margins and FR-21 threshold may need tuning. |
| 18 | Clone confirmation (open question 9). | Keep the y/N prompt for every clone, including private repos. | Extra keystroke if silent cloning is wanted. |
| 19 | Cache shape and privacy (open question 1). The brainstorm says the cache holds names, descriptions, visibility, timestamps only, but PR/issue titles (C1) and stats aggregates are also cached. | `~/.cache/claude-hub/repos.json` plus stats within it; PR/issue titles and aggregates treated as repo metadata, permitted under C-4; README/HANDOVER excerpts never cached. | Private PR titles sitting in `~` cache may be unacceptable; restrict to counts only. |
| 20 | S2 (wrap), S5 (`ctrl-r`), S7 (origin label, de-dup) are not in the 4b selection but are needed by selected features. | Included as FR-20, FR-3, FR-12. | Scope creep; remove FRs if unwanted. |
| 21 | v0 behaviours not mentioned in the brainstorm: `~` home row, `-n COUNT`, `--list`, hiding archived repos. | Retained unchanged. | Behaviour regressions or leftover clutter. |
| 22 | Refresh cadence and stale threshold (open question 6, S8). | Refresh on every launch plus `ctrl-r`; no timer; stale after 24 h. | Cache can be stale between launches; revisit pre-warm (C6). |
| 23 | Timeout and speed numbers are brainstorm targets, not measurements; 3 s per-repo timeout is a proposal. | Adopt as NFR targets; measure before sign-off. | Targets may be unattainable on cold cache with many repos. |
| 24 | Per-repo `claude_args` and extra flags (open question 12). | No flags; not implemented. | User must pass flags manually inside claude. |
| 25 | Sparkline and heatmap glyph rendering in the user's Ghostty font. | Use Unicode block characters (▁-█) and Nerd Font glyphs (as in the user's status bar), not emoji, to avoid fzf mis-measuring widths; no ASCII fallback. | Misrendered cells; add ASCII fallback. |
| 26 | What counts as an orphan. | An interactive `cli` session whose terminal is gone. Print-mode and SDK sessions (`entrypoint` other than `cli`, or `-p` / `--print` on the command line) are headless, not orphans; this was found when a real `claude -p` run was first reported as an orphan. | A genuinely abandoned print-mode run is not flagged. |
| 27 | A session is "attached" when an interactive registry entry's `parkedJobId` equals a background session's `jobId` (observed behaviour of Claude Code 2.1.x, not a documented contract). | Use it for the attached state and for the terminal shown. | If Claude Code changes the registry shape, attached sessions show as detached until updated. |
| 28 | Registry location and shape: `~/.claude/sessions/*.json` and `~/.claude/projects/*/*.jsonl`, also observed rather than documented. | Parse defensively; a malformed file is skipped. | Sessions may not appear after a Claude Code change. |
| 29 | Bulk threshold of 5000 changed lines in one commit. | Constant, not configurable yet. | A legitimate large feature commit is reported as bulk. |
| 30 | Tabs and splits are also new shells and therefore also open the picker. | Accept; Esc dismisses it. | If annoying, limit auto-launch to new windows (not selected). |
| 31 | Past sessions limited to the 40 most recent transcripts. | Keeps the view fast on large histories. | Older sessions are not listed. |
| 32 | "Other" is defined as plain folders and someone else's clones. | Anything not on the user's GitHub and not their own git repo. | A repo expected under Local appears under Other; adjust `owners` in the configuration. |
| 33 | The home row appears only on the All and Local tabs. | It is machine-level work, not a repository. | Missing from GitHub and Other, as intended. |
| 34 | A repo whose remote owner is not in `owners` is "someone else's" even if it is the user's fork. | Use `owners` to add further accounts. | A fork under another account shows `◇`. |
| 35 | `ctrl-l` skips sessions that are open in another terminal, headless, orphaned or stale, and picks the next resumable one. | Matches the documented behaviour that `--continue` refuses when the latest conversation is running in the background. | The "most recent" session by activity is not the one resumed; the preview shows which one will be. |
| 36 | The supported listing (`claude agents --json`) is treated as authoritative for running sessions; the registry and transcripts are enrichment. | Claude documents the listing as the supported interface and calls the transcript format internal. | If the listing omits a session type, the registry still shows it. |
| 37 | Quick terminal windows start in the home directory, so they still show the picker under the default auto-launch scope. | Accept; Esc dismisses it. | Set `CLAUDE_HUB_AUTOSTART=0` to stop it everywhere. |
| 38 | First launch into a folder Claude has not seen shows Claude's own workspace-trust dialog. | Normal Claude behaviour; there is no supported flag to skip it. | None. |

## 9. Requirements report

Revised 2026-10-13 after the mock-up review: FR-34 to FR-36 and AC-25 to AC-27 were added and FR-11 reworded. The counts in the report below are from the original authoring pass. Revised again on 2026-10-14 for the Sessions view, session badges, worktree grouping, bulk lines, auto-launch and the rename: FR-37 to FR-48, AC-28 to AC-38, NFR-8, C-9, decisions D-12 to D-16 and assumption rows 26 to 31 were added, and FR-3, FR-16 and FR-19 were reworded. The totals are now 48 FRs and 38 ACs.

```json
{
  "schema_version": "1",
  "report": {
    "agent": "requirements-author",
    "as_of_date": "2026-10-13",
    "scope": "claude-hub personal terminal launcher PRD from requirements-brainstorm.md, bin/claude-hub, the repo README, HANDOVER.md, context/*.md",
    "summary": "33 FRs, 7 NFRs, 8 constraints, 24 ACs, 25 assumption rows. One weak grade: feasible, evidenced by section-8 row 11 (fzf mechanisms unverified); row 12 also flags a Python-version conflict. No fail grades.",
    "verdict": "DONE-WITH-CONDITIONS",
    "sensitivity": "sensitive"
  },
  "grades": {
    "complete": "pass",
    "consistent": "pass",
    "feasible": "weak",
    "comprehensible": "pass",
    "able_to_be_validated": "pass"
  },
  "ears_conformant_count": 55,
  "assumptions_open_questions_count": 25
}
```
