#!/usr/bin/env python3
"""Emit the per-tool workspace anchors from the one canonical anchor body.

A workspace has one tool-agnostic memory body; each LLM tool auto-loads a different
entry file. This emitter renders the canonical anchor body once (token substitution)
and writes it to each tool's anchor destination, so the front doors can never silently
diverge. It is the cross-tool analogue of convert.py's per-tool agent emission.

Inputs: a target repo root + a dict of project values for the <angle-bracket> tokens
(<project-name>, <vault-path>, <repo-path>, <rules-pointer>, <date>). The v1 canonical
body uses a subset; supplying the full set keeps the emitter correct as the body grows.

Guarantees:
- Idempotent: re-running with the same values produces byte-identical files.
- Non-clobbering: writes ONLY the mapped anchor destinations (+ the sidecar), nothing else.
- Extensible: TOOL_ANCHORS is a tool -> {source, destination} table; adding a 4th
  tool is one entry. v1 all three share the one body.

Sidecar (anchor-sync hardening): alongside the anchors we write the exact token
`values` dict to `<repo_root>/.workspace/anchors.json`. The drift gate reads it back
as the canonical render's inputs instead of reverse-parsing the rendered CLAUDE.md
(which is lossy and fooled by a hand-edited heading). Written idempotently, content-
compared so a no-op re-emit leaves it untouched.

Wired so the Phase 3 scaffolder calls emit_workspace_anchors(); also runnable as a CLI.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Sidecar holding the exact token values used to render the anchors, so the drift
# gate has the canonical render's inputs without reverse-parsing CLAUDE.md.
SIDECAR_REL = Path(".workspace") / "anchors.json"

# A vendored copy of this tool carries the canonical anchor body as a sibling file
# (vendor_workspace.py writes it as `anchor-body.md` next to emit_anchors.py), so the
# tool resolves it with no catalog present.
VENDORED_ANCHOR = HERE / "anchor-body.md"

# The in-catalog canonical anchor body. The three per-tool templates beside the
# scaffolder are byte-identical, so any of them is the single source; we render from
# CLAUDE.md. This path only exists when running from inside the catalog.
CATALOG_ANCHOR = (
    ROOT
    / "plugins"
    / "workflow-agents"
    / "skills"
    / "engagement-scaffolder"
    / "templates"
    / "workspace"
    / "anchors"
    / "CLAUDE.md"
)


def canonical_anchor_path() -> Path:
    """Resolve the canonical anchor body, vendor-aware.

    Returns the first existing of: (a) a sibling `anchor-body.md` next to this script
    (the vendored case — works with no catalog present), then (b) the in-catalog
    template path (the dev/in-catalog case). Resolved at call time so a vendored copy
    with a sibling body resolves correctly even though the catalog path does not exist.
    Falls back to the catalog path (so callers get a clear missing-file error) when
    neither exists.
    """
    if VENDORED_ANCHOR.is_file():
        return VENDORED_ANCHOR
    return CATALOG_ANCHOR


# Adopter override (project-local, re-vendor-safe): literal text appended to the
# rendered anchor body. vendor_workspace never writes here.
ANCHOR_APPEND_REL = Path(".workspace") / "overrides" / "anchor-body.append.md"


def _apply_body_append(repo_root: Path | str, rendered: str) -> str:
    """Append the adopter's literal house content to an already-rendered body.

    Literal (no token substitution) so a stray <token> in the append can't crash the
    emit. Absent override file -> `rendered` unchanged. Used by BOTH the emitter and the
    gate's anchor-sync so the on-disk anchor and the re-render stay identical.
    """
    append = Path(repo_root) / ANCHOR_APPEND_REL
    if not append.is_file():
        return rendered
    return rendered.rstrip("\n") + "\n\n" + append.read_text(encoding="utf-8")


# tool -> {destination relative to the target repo root}. v1: all three render from the
# one canonical body (resolved at emit time via canonical_anchor_path). Add a tool by
# adding one entry.
TOOL_ANCHORS: dict[str, dict[str, object]] = {
    "claude": {"destination": Path("CLAUDE.md")},
    "codex": {"destination": Path("AGENTS.md")},
    "copilot": {
        "destination": Path(".github") / "copilot-instructions.md",
    },
}

_TOKEN = re.compile(r"<([a-z][a-z-]*)>")


def render_anchor_body(values: dict[str, str], *, template: str | None = None) -> str:
    """Render the canonical anchor body with <angle-bracket> tokens substituted.

    `values` keys are token names without the brackets (e.g. "project-name"). The
    canonical body is read from disk (vendor-aware, resolved at call time) unless an
    explicit `template` string is passed.
    """
    body = template if template is not None else canonical_anchor_path().read_text(encoding="utf-8")

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"emit_anchors: no value supplied for token <{key}>")
        return values[key]

    return _TOKEN.sub(repl, body)


def _write_sidecar(root: Path, values: dict[str, str]) -> Path:
    """Write the token `values` to `<root>/.workspace/anchors.json` (idempotent).

    The gate reads these back as the canonical render's inputs. Content-compared with
    a stable key order so a no-op re-emit leaves the file (and its mtime) untouched.
    """
    out = root / SIDECAR_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(values, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not out.exists() or out.read_text(encoding="utf-8") != content:
        out.write_text(content, encoding="utf-8")
    return out


def emit_workspace_anchors(repo_root: Path | str, values: dict[str, str]) -> list[Path]:
    """Render the canonical body once and write it to each tool's anchor destination.

    Returns the absolute paths actually written, read back from the mapping (so callers
    report the manifest from disk). Touches only the mapped destinations plus the
    `.workspace/anchors.json` sidecar; idempotent.
    """
    root = Path(repo_root)

    # Render once from the one canonical body (v1: one source for all three), resolved
    # vendor-aware at call time so a vendored copy works with no catalog present.
    # Apply any adopter body-append override (literal, no token substitution).
    content = _apply_body_append(root, render_anchor_body(values))
    written: list[Path] = []
    for spec in TOOL_ANCHORS.values():
        destination = spec["destination"]  # type: ignore[assignment]
        assert isinstance(destination, Path)
        out = root / destination
        out.parent.mkdir(parents=True, exist_ok=True)
        # Idempotent: only write when content differs, so a no-op re-emit leaves the
        # file (and its mtime) untouched and never produces a spurious diff.
        if not out.exists() or out.read_text(encoding="utf-8") != content:
            out.write_text(content, encoding="utf-8")
        written.append(out)

    # Write the sidecar the gate reads instead of reverse-parsing the rendered anchor.
    written.append(_write_sidecar(root, values))

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit per-tool workspace anchors from the canonical body.")
    parser.add_argument("repo_root", help="target repo root to write the anchors into")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--vault-path", required=True)
    parser.add_argument("--repo-path", default="")
    parser.add_argument("--rules-pointer", default="~/.claude/rules/")
    parser.add_argument("--date", default="")
    args = parser.parse_args(argv)

    values = {
        "project-name": args.project_name,
        "vault-path": args.vault_path,
        "repo-path": args.repo_path,
        "rules-pointer": args.rules_pointer,
        "date": args.date,
    }
    written = emit_workspace_anchors(args.repo_root, values)
    for path in written:
        print(f"wrote {path}")
    print(f"Emitted {len(written)} workspace anchor(s) from {canonical_anchor_path().name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
