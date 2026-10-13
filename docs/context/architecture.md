# Architecture

How the system is shaped — the major components and how they fit together.

One script, three stages:

1. **Collect** — local clones under `/mnt/data/github/` (`git log/status/rev-list`, in parallel) and
   `gh repo list jdk-official`, merged by repo name and sorted by latest activity.
2. **Pick** — `fzf` with a preview pane; row = name, where, visibility, age, state, description.
3. **Launch** — `cd` into the repo (cloning GitHub-only repos first, after a y/N prompt) and `exec claude`.

Planned: cache plus background refresh, git-stats header (streak, today/week), per-repo sparkline,
`hub stats` heatmap. See [requirements-brainstorm.md](../requirements-brainstorm.md).
