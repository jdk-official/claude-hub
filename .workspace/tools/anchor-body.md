# <project-name>

This is a thin anchor. The full project memory lives in the vault at
`<vault-path>` — this file only points there.

## At session start

Load cold-start context in one step: run `python .workspace/tools/recall.py` — it prints
HANDOVER + INDEX + ROUTER + tracking/ACTIVE + the memory index in one read, resolving the
vault from the sidecar. Or read those files yourself, in order:

1. `<vault-path>/INDEX.md` — the workspace map.
2. `<vault-path>/ROUTER.md` — task → which notes to load.
3. `<vault-path>/tracking/ACTIVE.md` — in-flight work.

Load only what the router sends you to — not the whole vault. Under Claude Code, native
memory also applies on top of this.

## Before you finish

Run the ROUTER capture step: update `<vault-path>/tracking/ACTIVE.md`, add an `adr/` entry if
you made a durable decision, and add a `reference/` pattern if a reusable
approach emerged.

## Governance

Follow the governance rules at `<rules-pointer>`.

---
Generated from the vault — do not hand-edit; update the vault and re-emit.
