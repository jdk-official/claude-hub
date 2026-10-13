# claude-hub

This is a thin anchor. The full project memory lives in the vault at
`/mnt/data/github/claude-hub/docs` — this file only points there.

## At session start

Load cold-start context in one step: run `python .workspace/tools/recall.py` — it prints
HANDOVER + INDEX + ROUTER + tracking/ACTIVE + the memory index in one read, resolving the
vault from the sidecar. Or read those files yourself, in order:

1. `/mnt/data/github/claude-hub/docs/INDEX.md` — the workspace map.
2. `/mnt/data/github/claude-hub/docs/ROUTER.md` — task → which notes to load.
3. `/mnt/data/github/claude-hub/docs/tracking/ACTIVE.md` — in-flight work.

Load only what the router sends you to — not the whole vault. Under Claude Code, native
memory also applies on top of this.

## Before you finish

Run the ROUTER capture step: update `/mnt/data/github/claude-hub/docs/tracking/ACTIVE.md`, add an `adr/` entry if
you made a durable decision, and add a `reference/` pattern if a reusable
approach emerged.

## Governance

Follow the governance rules at `/mnt/data/github/agent-catalog/plugins/governance/rules/`.

---
Generated from the vault — do not hand-edit; update the vault and re-emit.
