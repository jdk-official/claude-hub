#!/usr/bin/env python3
"""Reusable, scored workspace drift gate (Phase 2).

`reconcile.py` is bound to THIS repo's facts (plugin counts, agent notes). This
module is the portable analogue: point it at ANY instantiated workspace directory
and it returns a scored, blocking-vs-advisory split of drift findings. It enforces
the same rules (Grounding & Reconciliation, Dead Code, Dependency Justification)
against the canonical workspace layout the initialiser lays down.

Two buckets, by design:
- BLOCKING — deterministic checks (broken path/link/edge, index mismatch, dead
  command, missing/skewed dependency, untracked TODO, drifted anchor). These score
  AND decide pass/fail: the gate fails iff at least one blocking *error* is present.
  Blocking *warnings* lower the score but never fail the gate.
- ADVISORY — freshness only. Info level, lowers the score, NEVER changes pass/fail
  or the exit code. A stale-but-correct doc must not break a build. Divergence is
  scoped to **doc→code**: a doc whose referenced NON-markdown target (code, config,
  data) post-dates it. Doc→doc divergence (a doc pointing at a newer .md sibling) is
  deliberately not flagged — it is normal churn (e.g. INDEX→tracking/ACTIVE.md), not
  drift, and flagging it perpetually nagged every active workspace.

Scoring: start 100; -10 per error, -3 per warning, -1 per info; floored at 0.

Return shape (run_gate):
    {"score": int, "blocking": [finding...], "advisory": [finding...], "passed": bool}
where a finding is {"check", "severity", "target", "message"}.

Doc-vs-anchor scoping: the default layout is a *separate* vault (under Documents)
whose docs live apart from the repo that carries the anchors + `.workspace/anchors.json`
sidecar. So the doc-scanning checks (path, link, edges, index-sync, command,
dependency, version-skew, todo-fixme, freshness) scan the **vault** (`workspace_dir`),
while anchor-sync runs against the **repo** (`repo_root`). For a co-located workspace
the two coincide (`repo_root` defaults to `workspace_dir`), so behaviour is unchanged.

CLI:  python tools/workspace_drift.py <workspace_dir> [--repo <repo_root>]
      prints the report + score, exits non-zero iff a blocking error is present.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# Severity weights for scoring.
WEIGHTS = {"error": 10, "warning": 3, "info": 1}

# Checks whose findings decide pass/fail (vs the advisory bucket).
ADVISORY_CHECKS = {"freshness"}

# Workspace markdown lives in these (plus the root). Used to find docs to scan.
MARKDOWN_GLOB = "**/*.md"

# Anchor files an emitted workspace carries, mapped to their tool key. Reused for
# the anchor-sync check via emit_anchors.render_anchor_body.
ANCHOR_FILES = {
    "CLAUDE.md": "claude",
    "AGENTS.md": "codex",
    str(Path(".github") / "copilot-instructions.md"): "copilot",
}

# Dirs whose markdown contents an INDEX is expected to enumerate (the "indexed
# dirs" for the index-sync reverse check). Kept conservative: context/ is the
# durable-knowledge lane the canonical INDEX lists file-by-file.
INDEXED_DIRS = ("context",)

# Status docs that get the light calendar-age nudge (no code target to diverge from).
STATUS_DOCS = ("HANDOVER.md", str(Path("tracking") / "ACTIVE.md"))
STATUS_AGE_DAYS = 30

# Divergence requires the target to be newer than the doc by a meaningful margin.
# A scaffold writes all files within milliseconds; that write-ordering noise is not
# drift. Real "edited in a later session" divergence is minutes-plus.
FRESHNESS_MARGIN_SECONDS = 120.0

try:  # emit_anchors is a sibling tool; support both package and flat import.
    from tools.emit_anchors import SIDECAR_REL, render_anchor_body, _apply_body_append
except ModuleNotFoundError:  # pragma: no cover - exercised by flat-layout runs
    from emit_anchors import SIDECAR_REL, render_anchor_body, _apply_body_append


# --- override layer (project-local, re-vendor-safe) -------------------------
# The adopter owns <repo_root>/.workspace/overrides/; vendor_workspace never writes
# there. run_gate overlays gate.json on the core defaults; absent -> defaults.
OVERRIDES_REL = Path(".workspace") / "overrides"
GATE_OVERRIDE_REL = OVERRIDES_REL / "gate.json"


def _load_gate_overrides(repo_root: Path) -> dict:
    """Load <repo_root>/.workspace/overrides/gate.json, or {} if absent/invalid."""
    f = repo_root / GATE_OVERRIDE_REL
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _numeric(v) -> bool:
    """True for a real int/float (not bool) — used to reject mistyped override values."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# The check names this gate emits + the tunable keys an override may set. The
# override-staleness check validates gate.json against these so a renamed/removed
# core key surfaces instead of silently no-op'ing. Keep in sync with the checks below.
CHECK_NAMES = {
    "path", "broken-link", "edges", "index-sync", "command", "dependency",
    "version-skew", "todo-fixme", "anchor-sync", "freshness", "override-staleness",
}
THRESHOLD_KEYS = {"status_age_days", "freshness_margin_seconds"}
WEIGHT_KEYS = {"error", "warning", "info"}


def _check_override_staleness(repo_root: Path) -> list[dict]:
    """Advisory. Flag gate.json entries that reference a check/key core no longer has."""
    data = _load_gate_overrides(repo_root)
    if not data:
        return []
    rel = GATE_OVERRIDE_REL.as_posix()
    out: list[dict] = []
    for key in ("disabled_checks", "advisory_checks"):
        val = data.get(key)
        if val is None:
            continue
        if not isinstance(val, list):
            out.append(_finding("override-staleness", "info", rel,
                f"`{key}` must be a list; it is being ignored"))
            continue
        for name in val:
            if not isinstance(name, str):
                out.append(_finding("override-staleness", "info", rel,
                    f"`{key}` has a non-string entry; it is being ignored"))
                continue
            if name not in CHECK_NAMES:
                out.append(_finding("override-staleness", "info", rel,
                    f"`{key}` names unknown check `{name}` (renamed/removed in core?) - "
                    f"this override is currently a no-op"))
    for key, allowed, label in (("thresholds", THRESHOLD_KEYS, "tunable"),
                                ("weights", WEIGHT_KEYS, "severity key")):
        val = data.get(key)
        if val is None:
            continue
        if not isinstance(val, dict):
            out.append(_finding("override-staleness", "info", rel,
                f"`{key}` must be an object; it is being ignored"))
            continue
        for k, v in val.items():
            if k not in allowed:
                out.append(_finding("override-staleness", "info", rel,
                    f"`{key}.{k}` is not a known {label} (renamed/removed?)"))
            elif not _numeric(v):
                out.append(_finding("override-staleness", "info", rel,
                    f"`{key}.{k}` must be a number; the default is being used"))
    return out


# --- finding helpers --------------------------------------------------------

def _finding(check: str, severity: str, target: str, message: str) -> dict:
    return {"check": check, "severity": severity, "target": target, "message": message}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _markdown_files(root: Path) -> list[Path]:
    return sorted(p for p in root.glob(MARKDOWN_GLOB) if p.is_file())


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# --- frontmatter ------------------------------------------------------------

_FM_LINE = re.compile(r"^([A-Za-z][\w-]*):\s*(.+?)\s*$")


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, body). Mirrors lint.py's parser shape."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fields: dict[str, str] = {}
    for line in text[3:end].splitlines():
        m = _FM_LINE.match(line)
        if m:
            fields[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    body = text[end + 4:]
    return fields, body


# --- check 1: path (referenced workspace file that does not exist) ----------

# A backtick-quoted token that looks like a workspace path: has a slash OR ends in
# a markdown/known doc extension. Avoids flagging prose words or `npm run x`.
_BACKTICK = re.compile(r"`([^`\n]+)`")
_LOOKS_LIKE_PATH = re.compile(r"^[\w./-]+\.(?:md|markdown|json|ya?ml|toml|txt|py|ts|js)$")


def _check_path(root: Path, docs: list[Path]) -> list[dict]:
    out: list[dict] = []
    for doc in docs:
        _, body = _split_frontmatter(_read(doc))
        rel = _rel(doc, root)
        for m in _BACKTICK.finditer(body):
            token = m.group(1).strip()
            if "/" not in token and not token.endswith((".md", ".markdown")):
                continue  # bare filenames without a dir are too ambiguous to flag
            if not _LOOKS_LIKE_PATH.match(token):
                continue
            if not (root / token).exists():
                out.append(_finding("path", "error", rel,
                                     f"references workspace file `{token}` which does not exist"))
    return out


# --- check 2: broken markdown links -----------------------------------------

_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _is_local_link(target: str) -> bool:
    t = target.strip()
    if not t or t.startswith("#"):
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", t):  # http:, https:, mailto:, etc.
        return False
    return True


def _check_broken_links(root: Path, docs: list[Path]) -> list[dict]:
    out: list[dict] = []
    for doc in docs:
        rel = _rel(doc, root)
        for m in _MD_LINK.finditer(_read(doc)):
            target = m.group(1).split("#", 1)[0].split(" ", 1)[0].strip()
            if not _is_local_link(target):
                continue
            resolved = (doc.parent / target).resolve()
            if not resolved.exists():
                out.append(_finding("broken-link", "error", rel,
                                     f"link target `{target}` does not exist"))
    return out


# --- check 3: frontmatter edges (a key's value names a missing file) --------

def _check_edges(root: Path, docs: list[Path]) -> list[dict]:
    out: list[dict] = []
    for doc in docs:
        fm, _ = _split_frontmatter(_read(doc))
        rel = _rel(doc, root)
        for key, value in fm.items():
            value = value.strip()
            if not _LOOKS_LIKE_PATH.match(value):
                continue
            if not (root / value).exists() and not (doc.parent / value).exists():
                out.append(_finding("edges", "error", rel,
                                     f"frontmatter `{key}: {value}` names a file that does not exist"))
    return out


# --- check 4: index-sync ----------------------------------------------------

def _index_files() -> list[str]:
    return ["INDEX.md"]


def _check_index_sync(root: Path) -> list[dict]:
    out: list[dict] = []
    for pattern in ("INDEX.md", "*/INDEX.md"):
        for index in sorted(root.glob(pattern)):
            if not index.is_file():
                continue
            rel = _rel(index, root)
            text = _read(index)
            listed: set[str] = set()
            for m in _MD_LINK.finditer(text):
                target = m.group(1).split("#", 1)[0].split(" ", 1)[0].strip()
                if not _is_local_link(target):
                    continue
                resolved = (index.parent / target).resolve()
                listed.add(resolved.as_posix())
                if not resolved.exists():
                    out.append(_finding("index-sync", "error", rel,
                                         f"lists `{target}` which is not on disk"))
            # Reverse: a present file in an indexed dir the INDEX omits -> warning.
            for indexed_dir in INDEXED_DIRS:
                d = index.parent / indexed_dir
                if not d.is_dir():
                    continue
                for present in sorted(d.glob("*.md")):
                    if present.resolve().as_posix() not in listed:
                        out.append(_finding("index-sync", "warning", rel,
                                             f"omits present file `{_rel(present, root)}`"))
    return out


# --- check 5: command (npm run X / make X) ----------------------------------

_NPM_RUN = re.compile(r"npm run ([A-Za-z0-9:_-]+)")
_MAKE_TGT = re.compile(r"make ([A-Za-z0-9:_-]+)")


def _npm_scripts(root: Path) -> set[str] | None:
    pkg = root / "package.json"
    if not pkg.is_file():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return set((data.get("scripts") or {}).keys())


def _make_targets(root: Path) -> set[str] | None:
    mk = root / "Makefile"
    if not mk.is_file():
        return None
    targets: set[str] = set()
    for line in _read(mk).splitlines():
        m = re.match(r"^([A-Za-z0-9][\w.-]*)\s*:", line)
        if m:
            targets.add(m.group(1))
    return targets


def _check_command(root: Path, docs: list[Path]) -> list[dict]:
    out: list[dict] = []
    scripts = _npm_scripts(root)
    targets = _make_targets(root)
    for doc in docs:
        rel = _rel(doc, root)
        text = _read(doc)
        if scripts is not None:
            for m in _NPM_RUN.finditer(text):
                if m.group(1) not in scripts:
                    out.append(_finding("command", "error", rel,
                                         f"`npm run {m.group(1)}` is not a script in package.json"))
        if targets is not None:
            for m in _MAKE_TGT.finditer(text):
                if m.group(1) not in targets:
                    out.append(_finding("command", "error", rel,
                                         f"`make {m.group(1)}` is not a target in Makefile"))
    return out


# --- check 6 + 7: dependency present / version skew --------------------------

# "depend(s)/depending on `pkg`" or "we use `pkg`" — a deliberate dependency claim.
_DEP_REF = re.compile(r"depend(?:s|ing)? on `([A-Za-z0-9@/_.-]+)`", re.I)
# "`pkg` ... version `1.2.3`" / "pin `pkg` at `1.2.3`" — a pinned-version claim.
_VER_REF = re.compile(r"`([A-Za-z0-9@/_.-]+)`[^`\n]{0,40}?(?:version|at|pin(?:ned)?)[^`\n]{0,8}?`v?([0-9][\w.+-]*)`", re.I)
_VER_REF_ALT = re.compile(r"(?:version|at|pin(?:ned)?)[^`\n]{0,8}?`v?([0-9][\w.+-]*)`[^`\n]{0,40}?`([A-Za-z0-9@/_.-]+)`", re.I)


def _manifest_deps(root: Path) -> set[str] | None:
    pkg = root / "package.json"
    if not pkg.is_file():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps.update((data.get(key) or {}).keys())
    return deps


def _check_dependency(root: Path, docs: list[Path]) -> list[dict]:
    deps = _manifest_deps(root)
    if deps is None:
        return []
    out: list[dict] = []
    for doc in docs:
        rel = _rel(doc, root)
        for m in _DEP_REF.finditer(_read(doc)):
            name = m.group(1)
            if name not in deps:
                out.append(_finding("dependency", "error", rel,
                                     f"docs name dependency `{name}` absent from package.json"))
    return out


def _check_version_skew(root: Path, docs: list[Path]) -> list[dict]:
    # pkg -> {version: first-doc-that-pinned-it}
    seen: dict[str, dict[str, str]] = {}
    for doc in docs:
        rel = _rel(doc, root)
        text = _read(doc)
        for pkg, ver in _VER_REF.findall(text):
            seen.setdefault(pkg, {}).setdefault(ver, rel)
        for ver, pkg in _VER_REF_ALT.findall(text):
            seen.setdefault(pkg, {}).setdefault(ver, rel)
    out: list[dict] = []
    for pkg, versions in seen.items():
        if len(versions) > 1:
            where = ", ".join(f"{v} ({d})" for v, d in sorted(versions.items()))
            out.append(_finding("version-skew", "warning", pkg,
                                 f"`{pkg}` pinned to differing versions: {where}"))
    return out


# --- check 8: untracked TODO/FIXME ------------------------------------------

# A TODO/FIXME/XXX is "tracked" if followed by a ticket ref like (#123) or (ABC-12).
_TODO = re.compile(r"\b(TODO|FIXME|XXX)\b(\([^)]*\))?", re.I)
_TICKET = re.compile(r"\(\s*(#\d+|[A-Z]{2,}-\d+)\s*\)")


def _check_todo(root: Path, docs: list[Path]) -> list[dict]:
    out: list[dict] = []
    for doc in docs:
        rel = _rel(doc, root)
        for m in _TODO.finditer(_read(doc)):
            tail = m.group(2) or ""
            if _TICKET.match(tail):
                continue
            out.append(_finding("todo-fixme", "warning", rel,
                                 f"unresolved {m.group(1).upper()} with no ticket reference"))
    return out


# --- check 9: anchor-sync ----------------------------------------------------

def _anchor_token_values(root: Path) -> dict[str, str] | None:
    """Recover the project values an emitted anchor was rendered with.

    We re-render the canonical body and diff; to do that we need the same token
    values. Prefer the `.workspace/anchors.json` sidecar the emitter writes — it is
    the canonical render's exact inputs, so the gate compares against the true render
    rather than against values reverse-parsed out of the (possibly hand-edited)
    anchor. Fall back to reverse-parsing CLAUDE.md only when the sidecar is absent
    (back-compat with workspaces emitted before the sidecar existed). Skip (None) if
    neither yields values.
    """
    values = _sidecar_token_values(root)
    if values is not None:
        return values
    return _reverse_parsed_token_values(root)


def _sidecar_token_values(root: Path) -> dict[str, str] | None:
    """Read the exact token values from `<root>/.workspace/anchors.json`, or None."""
    sidecar = root / SIDECAR_REL
    if not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {str(k): str(v) for k, v in data.items()}


def _reverse_parsed_token_values(root: Path) -> dict[str, str] | None:
    """Back-compat fallback: recover values from the on-disk CLAUDE.md anchor.

    Reads the first heading (project-name) and the vault-path / rules-pointer lines.
    Lossy — a hand-edited heading is recovered as-is, so the re-render would match the
    edit and miss the drift. The sidecar exists precisely to avoid this; this path is
    only for workspaces emitted before the sidecar.
    """
    claude = root / "CLAUDE.md"
    if not claude.is_file():
        return None
    text = claude.read_text(encoding="utf-8")
    name = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    vault = re.search(r"vault at\s*\n`([^`]+)`", text)
    rules = re.search(r"governance rules at `([^`]+)`", text)
    if not (name and vault and rules):
        return None
    return {
        "project-name": name.group(1),
        "vault-path": vault.group(1),
        "repo-path": "",
        "rules-pointer": rules.group(1),
        "date": "",
    }


def _check_anchor_sync(root: Path) -> list[dict]:
    values = _anchor_token_values(root)
    if values is None:
        return []
    try:
        canonical = _apply_body_append(root, render_anchor_body(values))
    except KeyError:
        return []
    out: list[dict] = []
    for rel, _tool in ANCHOR_FILES.items():
        anchor = root / rel
        if not anchor.is_file():
            continue
        if anchor.read_text(encoding="utf-8") != canonical:
            out.append(_finding("anchor-sync", "error", rel,
                                 "anchor has drifted from the canonical body (hand-edited?); re-emit"))
    return out


# --- check 10: freshness (advisory) -----------------------------------------

def _git_commit_time(path: Path) -> float | None:
    """Last commit time (epoch) for a path, or None if not tracked / no git."""
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", path.name],
            cwd=str(path.parent), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _mtime(path: Path, *, prefer_git: bool) -> tuple[float, str]:
    """(timestamp, source). Prefer git commit time; fall back to filesystem mtime."""
    if prefer_git:
        ct = _git_commit_time(path)
        if ct is not None:
            return ct, "git"
    return path.stat().st_mtime, "fs"


def _referenced_targets(root: Path, doc: Path) -> set[Path]:
    """Local files this doc references (markdown links + frontmatter edges)."""
    text = _read(doc)
    fm, body = _split_frontmatter(text)
    out: set[Path] = set()
    for m in _MD_LINK.finditer(body):
        target = m.group(1).split("#", 1)[0].split(" ", 1)[0].strip()
        if _is_local_link(target):
            p = (doc.parent / target).resolve()
            if p.exists() and p.is_file() and p != doc.resolve():
                out.add(p)
    for value in fm.values():
        value = value.strip()
        if _LOOKS_LIKE_PATH.match(value):
            for base in (root, doc.parent):
                p = (base / value).resolve()
                if p.exists() and p.is_file() and p != doc.resolve():
                    out.add(p)
    return out


def _is_markdown(path: Path) -> bool:
    """A markdown target — divergence against these is doc→doc noise, not drift."""
    return path.suffix.lower() in (".md", ".markdown")


def _check_freshness(root: Path, docs: list[Path], *,
                     status_age_days: int = STATUS_AGE_DAYS,
                     freshness_margin_seconds: float = FRESHNESS_MARGIN_SECONDS) -> tuple[list[dict], str]:
    """Advisory. (a) doc→code divergence: a referenced NON-markdown target (code,
    config, data) newer than its referrer doc — the doc may describe stale behaviour.
    Divergence against another .md doc is deliberately skipped: a doc pointing at a
    perpetually-edited sibling doc (e.g. INDEX→tracking/ACTIVE.md) is normal, not drift.
    (b) light calendar-age nudge for status docs only. Returns (findings, source)."""
    # Decide the time source once, by probing whether git tracks the workspace.
    prefer_git = _git_commit_time(docs[0]) is not None if docs else False
    source = "git" if prefer_git else "fs"

    out: list[dict] = []
    for doc in docs:
        rel = _rel(doc, root)
        doc_ts, _ = _mtime(doc, prefer_git=prefer_git)
        # (a) doc→code divergence: only non-markdown targets count.
        diverged = False
        for target in _referenced_targets(root, doc):
            if _is_markdown(target):
                continue  # doc→doc is noise, not drift
            tgt_ts, _ = _mtime(target, prefer_git=prefer_git)
            if tgt_ts - doc_ts > freshness_margin_seconds:
                diverged = True
                break
        if diverged:
            out.append(_finding("freshness", "info", rel,
                                 f"referenced target changed more recently than this doc "
                                 f"(by {source} time); review for drift"))
            continue  # one freshness flag per doc is enough
        # (b) light calendar-age nudge, status docs only
        if rel in STATUS_DOCS:
            age_days = (time.time() - doc_ts) / 86400.0
            if age_days > status_age_days:
                out.append(_finding("freshness", "info", rel,
                                     f"status doc not touched in {int(age_days)} days "
                                     f"(by {source} time); confirm still current"))
    return out, source


# --- orchestration ----------------------------------------------------------

def run_gate(workspace_dir: Path | str, repo_root: Path | str | None = None) -> dict:
    """Run every check and return the scored, split result.

    Shape: {"score": int, "blocking": [...], "advisory": [...], "passed": bool}.
    `passed` is False iff at least one BLOCKING error exists; advisory items never
    affect it. Score starts at 100 and deducts per severity, floored at 0.

    Doc-scanning checks run against `workspace_dir` (the vault). The anchor-sync
    check runs against `repo_root` (the repo carrying the anchors + sidecar). For the
    co-located default `repo_root is None`, so it falls back to `workspace_dir` and
    both run against the one tree — unchanged behaviour.
    """
    vault = Path(workspace_dir).resolve()
    repo = Path(repo_root).resolve() if repo_root is not None else vault
    docs = _markdown_files(vault)

    ov = _load_gate_overrides(repo)
    # Each known key is honoured only when it has the right CONTAINER type — a
    # wrong-shape value (valid JSON, wrong type) falls back to the default rather than
    # crashing the gate; override-staleness surfaces it (Error Handling at Boundaries).
    ov_weights = ov.get("weights")
    weights = dict(WEIGHTS)
    if isinstance(ov_weights, dict):
        for _k, _v in ov_weights.items():
            if _k in WEIGHT_KEYS and _numeric(_v):
                weights[_k] = _v
    # 'override-staleness' is ALWAYS advisory (cannot be promoted to blocking).
    ov_advisory = ov.get("advisory_checks")
    advisory_base = ({x for x in ov_advisory if isinstance(x, str)}
                     if isinstance(ov_advisory, list) else set(ADVISORY_CHECKS))
    advisory_checks = advisory_base | {"override-staleness"}
    ov_disabled = ov.get("disabled_checks")
    disabled = ({x for x in ov_disabled if isinstance(x, str)}
                if isinstance(ov_disabled, list) else set())
    ov_thresholds = ov.get("thresholds")
    thresholds = ov_thresholds if isinstance(ov_thresholds, dict) else {}
    status_age = thresholds.get("status_age_days", STATUS_AGE_DAYS)
    if not _numeric(status_age):
        status_age = STATUS_AGE_DAYS
    fresh_margin = thresholds.get("freshness_margin_seconds", FRESHNESS_MARGIN_SECONDS)
    if not _numeric(fresh_margin):
        fresh_margin = FRESHNESS_MARGIN_SECONDS

    findings: list[dict] = []
    findings += _check_path(vault, docs)
    findings += _check_broken_links(vault, docs)
    findings += _check_edges(vault, docs)
    findings += _check_index_sync(vault)
    findings += _check_command(vault, docs)
    findings += _check_dependency(vault, docs)
    findings += _check_version_skew(vault, docs)
    findings += _check_todo(vault, docs)
    findings += _check_anchor_sync(repo)
    findings += _check_freshness(vault, docs, status_age_days=status_age,
                                 freshness_margin_seconds=fresh_margin)[0]
    findings += _check_override_staleness(repo)

    findings = [f for f in findings if f["check"] not in disabled]
    blocking = [f for f in findings if f["check"] not in advisory_checks]
    advisory = [f for f in findings if f["check"] in advisory_checks]

    # int() keeps the documented {"score": int} contract even if an override sets a
    # float weight (a deliberately-accepted value, not a malformed shape).
    deduction = sum(weights[f["severity"]] for f in findings)
    score = max(0, 100 - int(deduction))
    passed = not any(f["severity"] == "error" for f in blocking)

    return {"score": score, "blocking": blocking, "advisory": advisory, "passed": passed}


def exit_code(result: dict) -> int:
    """0 iff the gate passed (no blocking error); 1 otherwise. Advisory never fails."""
    return 0 if result["passed"] else 1


def _format_report(root: Path, result: dict) -> str:
    lines = [f"Workspace drift gate - {root}", ""]
    for label, bucket in (("BLOCKING", result["blocking"]), ("ADVISORY", result["advisory"])):
        lines.append(f"{label} ({len(bucket)}):")
        if not bucket:
            lines.append("  (none)")
        for f in bucket:
            lines.append(f"  [{f['severity']}] {f['check']} - {f['target']}: {f['message']}")
        lines.append("")
    verdict = "PASS" if result["passed"] else "FAIL"
    lines.append(f"Score: {result['score']}/100   Verdict: {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scored workspace drift gate (blocking + advisory).")
    ap.add_argument("workspace_dir", help="path to the instantiated workspace (vault) directory")
    ap.add_argument(
        "--repo",
        default=None,
        help="repo root carrying the anchors + .workspace/anchors.json sidecar "
        "(default: the workspace_dir, i.e. a co-located workspace)",
    )
    ap.add_argument("--json", action="store_true", help="emit the raw result as JSON")
    args = ap.parse_args(argv)

    root = Path(args.workspace_dir)
    if not root.is_dir():
        print(f"workspace_drift: not a directory: {root}", file=sys.stderr)
        return 2

    repo = Path(args.repo) if args.repo is not None else None
    if repo is not None and not repo.is_dir():
        print(f"workspace_drift: --repo is not a directory: {repo}", file=sys.stderr)
        return 2

    result = run_gate(root, repo)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(_format_report(root.resolve(), result))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
