# fzf spike (Q1): what iteration 2 can rely on

Date: 2026-10-13. fzf 0.74.3. Reproduce with `python3 tests/spikes/fzf_spike.py`; it drives real fzf in a
tmux pane. Result: 11 of 11 checks pass. This settles assumption row 11 of the PRD.

## Verified mechanisms

| Need | Mechanism | Result |
|---|---|---|
| Stats header above the prompt (FR-35) | `--header-first` with `--layout reverse` | Header row renders above the prompt row |
| Key-hint footer (FR-35) | `--footer TEXT` | Renders |
| Search name and tags only (FR-34) | `--with-nth 1,2 --nth 1` over tab-separated name and columns | A query that matches only a column matches nothing; a name query finds the row |
| In-place background refresh (FR-2, FR-3) | `--listen PORT --track --id-nth 1`, then POST `reload(cmd)` | Highlighted row and typed query both survive; new rows appear |
| Update stats without redraw (FR-35) | POST `change-header(text)` to `--listen` | Header changes in place |
| Launch without a second process step | `--bind 'enter:become(cmd {3})'` | Runs with the selected row's field and replaces fzf |
| Resume key (FR-24) | `--expect ctrl-l` (current approach) | Key is returned with the selection |
| Responsive preview (FR-21/22) | `--preview-window 'right,45%,<45(down,40%)'` | Covered by the end-to-end tests: below at 60 columns, beside at 150 |

## Findings that change the plan

1. **`--with-nth 2 --nth 1` does not work.** `--nth` indexes the transformed line, and a single display field has
   no delimiter inside it, so every column is still searched. Emit name and columns as separate tab fields and use
   `--with-nth 1,2 --nth 1`.
2. **`--listen` needs a readiness wait.** The HTTP server is not up the instant fzf starts; the first request can be
   refused. Retry briefly (the spike polls up to 3 s).
3. **`<N` in `--preview-window` is the preview pane's width**, not the terminal's. At 45% it means a terminal under
   100 columns when N is 45. Already fixed in `bin/claude-hub`.
4. **Order of actions matters under `--track`.** An action queued after `reload` (for example `change-header` or
   `transform-header`) is silently dropped while fzf searches for the tracked row. Put the header update before
   the reload: `transform-header(...)+reload(...)`. This cost an end-to-end test failure to find.
5. **`execute-silent` is synchronous**, so `execute-silent(cmd)+transform-header(...)+reload(...)` is the way to
   write state first and then rebuild from it.
6. **Reload needs identity.** Without `--track --id-nth 1` the cursor jumps to the top on reload.

## Consequences for iteration 2

- Q3 (header and footer): `--header-first` plus `--footer`; update stats text with `change-header`.
- Q4 (search): switch the field layout to `name \t columns \t path \t slug` with `--with-nth 1,2 --nth 1`.
- Q5 (in-place refresh): start fzf with `--listen`, run the refresh in the background, then POST `reload(...)` and
  `change-header(...)`. `ctrl-r` posts the same reload.
- Port selection: bind a free port at launch and pass it to the refresher; never listen on a non-loopback address.

## Reliability of the spike script

The spike script (tests/spikes/fzf_spike.py in the repo) drives real fzf in tmux and reads the screen. On an idle machine it passes 13/13
repeatedly. On a heavily loaded machine (several test suites and Claude sessions at once) one or two checks
occasionally fail because the screen is read before fzf has finished drawing or filtering, and the failing check
changes from run to run. It waits for the list, for typed text to appear, and for result counts, and retries
`--listen` ports, but it cannot remove load-induced timing. If it shows 12/13 or 11/13, re-run it when the machine
is quiet before treating it as a regression. It is a diagnostic, not part of the test suite: the end-to-end tests
use the same waiting approach and have been stable.

