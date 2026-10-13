# hub: requirements brainstorm

Status: draft for review. Based on `bin/hub` (~165 lines) as of 2026-10-13. Nothing here is implemented or tested.

## 1. Goal and user story

hub is a one-keystroke launcher: open a terminal, see my recent repos, pick one, and be inside
`claude` in the right directory within a second or two.
As the sole user, I want to pick a recent project (local or GitHub-only) from a narrow tiled
Ghostty window and start or resume a Claude session there, so that I never type `cd` or `gh repo clone`.

## 2. Requirements (EARS-style)

### MUST

| ID | Requirement | Acceptance check |
|----|-------------|------------------|
| M1 | When hub starts, the system shall show the picker from a local cache without waiting for GitHub. | With `gh` replaced by `sleep 30`, picker is visible and usable in under 1 s. |
| M2 | While the picker is open, the system shall refresh GitHub data in the background and update the list when it arrives. | After a repo is pushed from another machine, it appears (or re-sorts) within one refresh, no restart. |
| M3 | When a row is selected and Enter pressed, the system shall `cd` to the repo and exec `claude`. | `pwd` in the claude session equals the repo path; hub process is gone (exec). |
| M4 | When a GitHub-only repo is selected, the system shall ask before cloning into `/mnt/data/github/<name>` and abort cleanly on "n" or clone failure. | Answer "n": nothing on disk. Forced failure: non-zero exit, no partial dir left. |
| M5 | While the terminal is narrow (<= 60 columns), the system shall show every row's name and state without horizontal scrolling or mid-word truncation of the repo name. | At 50 columns, each row fits one line; name is intact; preview shows below, not beside. |
| M6 | If `gh` is missing, unauthenticated, offline, or times out, the system shall still list local repos and say so in one header line. | Run with `PATH` lacking `gh`: picker opens, header says "GitHub unavailable (cached Nh ago)" or "local only". |
| M7 | If `fzf` or `claude` is missing, the system shall exit non-zero with a one-line message naming the missing tool and how to install it. | `PATH=/usr/bin/false-dir hub` prints one line, exit code 127-ish, no traceback. |
| M8 | The system shall never write credentials, tokens, or `gh` output beyond repo metadata outside `~`. | Cache lives in `~/.cache/hub/`; `grep -r` for token strings under `/mnt/data` finds none. |

### SHOULD

| ID | Requirement | Acceptance check |
|----|-------------|------------------|
| S1 | When a repo is highlighted, the preview shall show last 3 commits (subject + age) and the first ~10 lines of `HANDOVER.md`, else the repo README. | Highlight a repo with HANDOVER.md: its first lines show; one without shows README. |
| S2 | When the preview pane renders, the system shall word-wrap description and paths to the pane width (never clip). | Resize to 50, 80, 120 columns: no line exceeds pane width, no text lost. |
| S3 | When the user presses a resume key (proposed `ctrl-r`), the system shall exec `claude --continue`; plain Enter starts a new session. | `ctrl-r` in a repo with a prior session reopens it; Enter opens a blank one. |
| S4 | When the user presses `ctrl-o`, the system shall open the repo's GitHub page in the browser (`gh browse`); `ctrl-s` shall open a plain `$SHELL` in the repo. | Each key does only its action; hub exits afterwards. |
| S5 | When the user presses `ctrl-g` (refresh), the system shall re-run the GitHub fetch and local git scan and redraw. | Make a repo dirty in another terminal, press key, `*N` appears. |
| S6 | The system shall read `~/.config/hub/config` for owners, extra source dirs, pinned and hidden repos, and count. | Add `hidden = foo`: `foo` no longer listed; pinned repo sorts first. |
| S7 | Where several sources exist, the system shall label each row with its origin (github owner or dir) and de-duplicate by remote URL, not just by name. | Two repos named `x` from different owners both appear, distinguishable. |
| S8 | If the cache is older than a threshold (default 24 h), the system shall mark it as stale in the header. | Age the cache file with `touch -d`: header shows "stale". |

### COULD

| ID | Requirement | Acceptance check |
|----|-------------|------------------|
| C1 | The preview shall include open PR and issue counts (titles for the top 3), fetched lazily and cached. | Repo with 2 open PRs shows "2 PRs" and titles after a moment. |
| C2 | The system shall support `/mnt/data/files` and `/mnt/data/scratch` as non-git directory sources (age by mtime). | A scratch dir without `.git` is listed and launchable. |
| C3 | The system shall offer a "new scratch dir" action that creates `/mnt/data/scratch/<date>-<slug>` and launches there. | Action creates the dir and starts claude in it. |
| C4 | The system shall support `--list --json` for scripting and a `-q QUERY` pre-filter. | `hub --list --json | jq length` works; `hub -q hub` preselects. |
| C5 | A Hyprland keybind (e.g. `SUPER+ALT+Return`) shall launch `ghostty -e hub` as a floating/centred window. | Keybind opens hub; `hyprctl configerrors` is empty. |
| C6 | The system shall pre-warm the cache at login (systemd user timer or Hyprland `exec-once`). | After login, cache mtime is under 15 min old. |

## 3. Non-functional requirements

- Startup: picker visible in <= 300 ms with warm cache, <= 1 s cold-cache local-only. Local git scans run in parallel (as today) and must not block first paint beyond that budget (measure; unverified).
- Background refresh: GitHub call timeout 20 s, never blocks input, and fails silently apart from the header note.
- Offline: fully usable with the last cache plus live local git state; clone of a GitHub-only repo is refused with a clear message when offline.
- Narrow terminal: design for ~384 px / roughly 45-55 columns (exact column count at the user's font size is unverified; confirm with `tput cols` inside the window). Single-line rows, preview below at 40% height, toggled with `?` or `ctrl-/`. Fall back to side-by-side preview at >= 100 columns.
- Width handling: truncate the description (with an ellipsis) in the list row only; the full text appears wrapped in the preview.
- Missing tools: `gh` absent or unauthenticated degrades to local-only (M6). `fzf` and `claude` absent are fatal with an install hint (M7). `git` absent is fatal. Python version below 3.8 is fatal with a message.
- Resilience: a corrupt or unreadable cache is ignored and rebuilt, never fatal. A repo whose `git` call hangs is skipped after a per-repo timeout (today 15 s; propose 3 s).
- Safety: hub performs no destructive git operation (no push, reset, clean, force). Clone always asks first.
- Privacy: cache holds names, descriptions, visibility, timestamps only. No tokens, no private repo contents (README/HANDOVER excerpts are read live from disk, not cached).
- Footprint: stdlib-only Python, single file, no pip dependencies.

## 4. Open questions (recommended default in bold)

1. Cache location and format? **`~/.cache/hub/repos.json` (home, not the data drive, per the secrets rule).**
2. Does Enter start new or resume? **New session on Enter, `ctrl-r` resumes; revisit if you resume more than 70% of the time.**
3. Which owners? **Only `jdk-official` for now; config key `owners = [...]` ready for more.** Do you want org repos or collaborator repos included?
4. How many rows? **Keep 10 by default, but let fzf scroll and search the full cached list (up to 100) so a repo outside the top 10 is still reachable by typing.** Today `-n` hides everything past 10.
5. Sort order? **Most recent activity (max of last commit and push), pinned first.** Should dirty working trees outrank age?
6. Refresh cadence? **Refresh on every launch in the background, plus a manual key; no timer.** Is a login pre-warm worth a systemd unit (C6)?
7. Window style? **Floating, centred, about 60 columns by 20 rows, via a Hyprland window rule on a class or title.** Or keep the tiled 384 px window?
8. Where does the config file live and can it hold secrets? **`~/.config/hub/config` (TOML), non-secret only; auth stays with `gh`.**
9. Clone confirmation? **Keep the y/N prompt.** Or clone silently for private repos you own?
10. Non-git dirs (`files`, `scratch`)? **Defer; add as C2 after the core is solid.**
11. Language and stack? **Stay with Python stdlib + fzf (works today, no deps).** A rewrite in Go or Rust would only pay off if startup is still too slow after caching.
12. Launch `claude` with extra flags (model, permission mode, `--add-dir`)? **No flags by default; optional per-repo `claude_args` in config.**

## 4b. Selected scope (chosen by the user, 2026-10-13)

From the 25-feature brainstorm, these were selected. Existing requirement IDs are cross-referenced.

| Feature | Maps to | Notes |
|---------|---------|-------|
| Cached list, background refresh | M1, M2, S8 | Core of the first iteration. |
| Fuzzy search over all repos | Open question 4 | Search the full cached list (up to 100); display stays at 10 until typed. |
| Pinned and hidden repos | S6 | Config file. |
| Extra scan roots (`/mnt/data/files`, `/mnt/data/scratch`) | C2 | Promoted from COULD to SHOULD. |
| Tags and groups | new (T1) | Tag in config; filter key in the picker. |
| "Needs attention" sort | new (A1) | Dirty, unpushed, or open PR floats up; this resolves open question 5 toward dirty-first. |
| Open PRs and issues in preview | C1 | Promoted from COULD to SHOULD. |
| HANDOVER / README excerpt | S1 | |
| Resume vs new session | S3 | |

### Gamification (git stats)

Local, offline, derived from `git log` across scanned clones. Purpose: make steady building visible.

| ID | Requirement | Acceptance check |
|----|-------------|------------------|
| G1 | The header shall show the current streak (consecutive days with at least one authored commit) and the best streak. | Commit today in any scanned repo: streak increments once; a gap day resets it. |
| G2 | The header shall show today and this week: active repos, commits, and lines changed, against the user's own 4-week average. | Numbers match `git log --author --since` summed over the scanned repos. |
| G3 | The preview shall show a per-repo sparkline of commits per week for the last 8 weeks. | A repo with no commits for 8 weeks shows a flat line; one active week shows one tall bar. |
| G8 | `hub stats` shall print a 12-week contribution heatmap in the terminal. | Each cell matches that day's authored-commit count; output fits 80 columns. |

Counting rules (defaults, to confirm):
- Count commits authored by `jonathan@kyte.me.uk` or the GitHub noreply address; exclude bots.
- Commits with a `Co-Authored-By: Claude` trailer count (the user directed the work).
- Streaks and goals count active days, not raw commits, so splitting a change into many commits does not pay.
- Scope is local clones only; GitHub-only repos are excluded (would need an API call per repo).
- Computed from git on each refresh and cached with the repo list under `~/.cache/hub/`; no network.

Deferred from the brainstorm (not selected): ship counter, badges and milestones, weekly goal, finish-line nudge.

## 5. Non-goals

- Not a general file manager, project manager, or task tracker.
- Not a git client: no commit, push, pull, rebase, branch switch, or PR creation from hub.
- Not a multi-user or shared tool; no server, daemon, or network service of its own.
- Not a Claude session browser or transcript viewer (only new vs `--continue`).
- No GUI, no TUI framework beyond fzf, no mouse-driven UI.
- No management of secrets, tokens, SSH keys, or `gh` auth.
- No support for non-GitHub forges (GitLab, Gitea) or Windows/macOS in this iteration.
- No automatic cloning, pulling, or deleting of repos in the background.
- No editing of Hyprland or Ghostty configs from hub; keybinding setup is a documented one-off step.

## Unverified

Timings above are targets, not measurements. Column count of the tiled window, `claude --continue`
behaviour per directory, and fzf's `--preview-window down` / `change-preview-window` bindings on the
installed fzf version should each be checked before implementation.
