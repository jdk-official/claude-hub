# 0001 Order the list by last use

Date: 2026-10-18. Status: accepted (supersedes PRD D-8).

The list was pinned, then needs-attention, then recency of commit or push. In use it read as unordered: dirty
repos jumped ahead of what you had just been working in. Order is now pinned, then most recently used, where use is
the latest of last commit, last push and the newest Claude session transcript for that directory (worktrees feed
their parent). Dirty, unpushed and PR state stays visible as row markers.

## Tabs: Projects, Other, Sessions

All, Local and GitHub were three filters on one merged list, so they are one Projects tab (local, GitHub and both,
plus worktrees). Other (plain folders, other people's clones) and Sessions stay. Old `start_tab` values `all`, `local`
and `github` are read as `projects`. Keys: ctrl-s / alt-s cycle, alt-1..3 jump.

## Tab dashboards

Sessions leads with a "needs you" row (orphaned, stale, and detached sessions idle a day or more), Other with a "stale"
row (folders untouched 90 days, unsaved work flagged, a `hidden = [...]` line to paste). Both are informational: Enter
does nothing on them. Chosen because each leads to an action; activity charts and size breakdowns were left out.
