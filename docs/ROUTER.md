# hub — task router

Load only what the task needs — not the whole workspace. Find your task below,
load the listed notes, then do the work. Capture what you learned at the end.

## If the task is…

| Task | Load these notes |
|---|---|
| **Understand the project** | [context/architecture.md](context/architecture.md), [context/stack.md](context/stack.md), [HANDOVER.md](HANDOVER.md) |
| **Add or change a feature** | [context/architecture.md](context/architecture.md), [context/conventions.md](context/conventions.md), the relevant spec in `specs/`, the relevant plan in `plans/` |
| **Fix a bug** | [context/conventions.md](context/conventions.md), [tracking/ACTIVE.md](tracking/ACTIVE.md), any matching pattern in `reference/` |
| **Make a decision** | [context/decisions.md](context/decisions.md), [adr/README.md](adr/README.md), prior records in `adr/` |
| **Resume cold** | [HANDOVER.md](HANDOVER.md), [tracking/ACTIVE.md](tracking/ACTIVE.md), then this router |

## Capture (after the work)

Before you finish, fold what you learned back in so the next session starts ahead:

- Update [tracking/ACTIVE.md](tracking/ACTIVE.md) — status of what you moved.
- If you made a durable decision, add an entry under `adr/` (see [adr/README.md](adr/README.md)).
- If a reusable approach emerged, add a pattern note under `reference/`.
