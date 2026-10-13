#!/usr/bin/env python3
"""Assemble the cold-start recall bundle from a workspace vault — one command, any tool.

Cold-start "recall" on a non-Claude tool today means an agent *reading* the right files
from a prose instruction. This makes it a deterministic one command any tool can run:
point it at a vault (or let it resolve the vault from the vendored sidecar) and it prints
the ordered cold-start set as one bundle, so an agent gets the whole context in one read.
Claude Code keeps its native memory as a bonus on top; every other tool gets this.

Default ordered set (the cold-start essentials):
    HANDOVER.md, INDEX.md, ROUTER.md, tracking/ACTIVE.md, memory/MEMORY.md

Override: if `<repo>/.workspace/recall.json` exists (a JSON list of vault-relative paths),
that order is used instead. Absent → the default set.

Vault resolution: an explicit `vault` arg wins; otherwise the `vault-path` is read from the
sidecar beside the vendored tool (`<recall.py's dir>/../anchors.json`, i.e.
`.workspace/anchors.json`), so a vendored `python .workspace/tools/recall.py` with no arg
just works. If neither yields a vault, exit non-zero with a clear message.

Stdlib only (argparse / json / pathlib / sys). Runnable as a CLI:
    python .workspace/tools/recall.py            # vendored: vault from the sidecar
    python tools/recall.py <vault> [--repo R]    # explicit vault (+ optional repo override)
    python tools/recall.py <vault> --json        # machine-readable bundle
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The documented default cold-start set, in load order. HANDOVER first (the snapshot),
# then the map, the router, in-flight work, and the memory index.
DEFAULT_RECALL_SET = (
    "HANDOVER.md",
    "INDEX.md",
    "ROUTER.md",
    "tracking/ACTIVE.md",
    "memory/MEMORY.md",
)

# Optional per-repo override of the recall set (JSON list of vault-relative paths).
RECALL_OVERRIDE_REL = Path(".workspace") / "recall.json"

# The sidecar emit_anchors.py writes beside the vendored tools; carries `vault-path`.
SIDECAR_NAME = "anchors.json"


class RecallError(Exception):
    """Raised when the vault cannot be resolved or read."""


def _recall_order(repo: Path | None) -> list[str]:
    """The ordered relative paths to assemble: the override if present, else the default."""
    if repo is not None:
        override = Path(repo) / RECALL_OVERRIDE_REL
        if override.is_file():
            try:
                loaded = json.loads(override.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RecallError(f"recall: invalid JSON in {override}: {exc}") from exc
            if not isinstance(loaded, list) or not all(isinstance(p, str) for p in loaded):
                raise RecallError(f"recall: {override} must be a JSON list of vault-relative paths")
            return loaded
    return list(DEFAULT_RECALL_SET)


def resolve_vault(vault: Path | str | None, *, tool_dir: Path | str | None = None) -> Path:
    """Resolve the vault: explicit arg wins; else read `vault-path` from the sidecar.

    The sidecar sits at `<tool_dir>/../anchors.json` — i.e. `.workspace/anchors.json` when
    the tool is vendored to `.workspace/tools/`. `tool_dir` defaults to this script's dir.
    Raises RecallError when neither an explicit vault nor a sidecar `vault-path` is found.
    """
    if vault is not None:
        return Path(vault)

    base = Path(tool_dir) if tool_dir is not None else HERE
    sidecar = base.parent / SIDECAR_NAME
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RecallError(f"recall: invalid JSON in sidecar {sidecar}: {exc}") from exc
        vault_path = data.get("vault-path") if isinstance(data, dict) else None
        if vault_path:
            return Path(vault_path)

    raise RecallError(
        "recall: no vault given and none resolvable from the sidecar "
        f"({sidecar}). Pass a vault path explicitly."
    )


def assemble_bundle(
    vault: Path | str, *, repo: Path | str | None = None
) -> dict[str, object]:
    """Assemble the cold-start bundle from `vault` in the recall order.

    The order is the `.workspace/recall.json` override under `repo` if present, else the
    default set. Each entry records its vault-relative path, whether it exists, and its
    content (empty string when absent). Missing files are noted, never fatal.
    """
    vault_path = Path(vault)
    repo_path = Path(repo) if repo is not None else None

    files: list[dict[str, object]] = []
    for rel in _recall_order(repo_path):
        target = vault_path / rel
        exists = target.is_file()
        content = target.read_text(encoding="utf-8") if exists else ""
        files.append({"path": rel, "exists": exists, "content": content})

    return {"vault": str(vault_path), "files": files}


def render_bundle(bundle: dict[str, object]) -> str:
    """Render the bundle as concatenated text: each file under a `===== <relpath> =====` rule.

    The delimiter is deliberately NOT a markdown heading, so it never collides with `#`/`##`
    headings inside the recalled files — the bundle stays unambiguously segmentable (grep
    `^===== `). Missing files get a `(not present)` body so the reader sees the gap.
    """
    parts: list[str] = []
    files = bundle["files"]
    assert isinstance(files, list)
    for entry in files:
        rel = entry["path"]
        parts.append(f"===== {rel} =====")
        if entry["exists"]:
            body = str(entry["content"]).rstrip("\n")
            parts.append(body)
        else:
            parts.append("(not present)")
        parts.append("")  # blank line between sections
    return "\n".join(parts).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble and print the cold-start recall bundle from a workspace vault."
    )
    parser.add_argument(
        "vault",
        nargs="?",
        help="vault directory. If omitted, resolved from the sidecar (.workspace/anchors.json).",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="repo root to read the .workspace/recall.json override from (default: the vault).",
    )
    parser.add_argument("--json", action="store_true", help="emit the bundle as JSON.")
    args = parser.parse_args(argv)

    # Workspace markdown legitimately carries non-ASCII (→, em-dashes); force UTF-8 on
    # stdout so the bundle prints on a Windows console whose default codec is cp1252.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass

    try:
        vault = resolve_vault(args.vault)
    except RecallError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Default the override-source repo to the vault (co-located case) when not given.
    repo = args.repo if args.repo is not None else vault
    try:
        bundle = assemble_bundle(vault, repo=repo)
    except RecallError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(bundle, indent=2, ensure_ascii=False))
    else:
        print(render_bundle(bundle), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
