#!/usr/bin/env python3
"""Regenerate docs/screenshots/*.png from a throwaway demo sandbox.

Builds made-up repos, GitHub listings and Claude sessions under /tmp/demo (nothing of yours is read or shown), drives
the real picker in tmux, captures each screen with its colours, and renders it to PNG with headless Chromium.

Needs: tmux, fzf, git, chromium, and ImageMagick (magick) to trim the margins.
Run:   python3 scripts/screenshots.py
"""
import html
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = os.path.join(ROOT, "bin", "claude-hub")
OUT = os.path.join(ROOT, "docs", "screenshots")
BASE = "/tmp/demo"
COLS, ROWS = 140, 26
FONT = "JetBrainsMono Nerd Font, JetBrainsMono NF, Noto Sans Mono, monospace"

FAKE_CLAUDE = "#!/bin/sh\nexit 0\n"
FAKE_GH = """#!/bin/sh
case "$1 $2" in
  "repo list") cat "$DEMO_GH_REPOS"; exit 0 ;;
  "api rate_limit") exit 0 ;;
  "pr list") echo '[{"title":"Add a weekly meal planner view"}]'; exit 0 ;;
  *) echo '[]'; exit 0 ;;
esac
"""

# name, minutes since last commit, commits in the last 12 weeks, dirty files, tag
CLONED = [
    ("recipe-box", 6, 38, 2, "work"),
    ("weather-cli", 190, 21, 0, "tools"),
    ("trail-planner", 26 * 60, 33, 0, "work"),
    ("budget-tracker", 50 * 60, 17, 0, "home"),
    ("dotfiles", 9 * 24 * 60, 12, 0, "tools"),
]
LOCAL_ONLY = [("garden-notes", 19 * 24 * 60, 6, 0, "home")]
GITHUB_ONLY = [("photo-sorter", 5 * 24 * 60, "Sort photos by date and place"),
               ("bookmark-sync", 21 * 24 * 60, "Sync bookmarks between browsers")]
DESCRIPTIONS = {
    "recipe-box": "Recipe manager with a meal planner", "weather-cli": "Forecasts in your terminal",
    "trail-planner": "Plan walking routes", "budget-tracker": "Track spending by category",
    "dotfiles": "My shell and editor config",
}
PRS = {"budget-tracker": 2, "recipe-box": 1}
OWNER = "demo-user"


def sh(args, cwd=None, env=None, check=True):
    e = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    e.update(env or {})
    return subprocess.run(args, cwd=cwd, env=e, check=check, capture_output=True, text=True)


def commit(path, when, msg, n):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(when))
    with open(os.path.join(path, "notes.txt"), "a") as f:
        f.write("\n".join(f"line {n}.{i}" for i in range(1 + n % 4)) + "\n")
    sh(["git", "add", "-A"], path)
    sh(["git", "-c", "user.name=Demo User", "-c", "user.email=demo@example.com", "commit", "-q", "-m",
        msg + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>"], path,
       env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})


def make_repo(path, last_minutes_ago, commits, remote=None, dirty=0):
    os.makedirs(path)
    sh(["git", "init", "-q", "-b", "main"], path)
    now = time.time()
    rnd = random.Random(os.path.basename(path))
    last = now - last_minutes_ago * 60
    span = 84 * 86400
    times = sorted(last - rnd.random() * span for _ in range(commits - 1)) + [last]
    for i, t in enumerate(times):
        t = min(t, last)
        commit(path, t, f"Update {i}", i)
    if remote:
        sh(["git", "remote", "add", "origin", remote], path)
    for i in range(dirty):
        with open(os.path.join(path, f"wip-{i}.txt"), "w") as f:
            f.write("work in progress\n")


def build():
    shutil.rmtree(BASE, ignore_errors=True)
    code, scratch = os.path.join(BASE, "code"), os.path.join(BASE, "scratch")
    for d in (code, scratch, os.path.join(BASE, "bin"), os.path.join(BASE, "cache"), os.path.join(BASE, ".claude", "sessions"),
              os.path.join(BASE, ".claude", "projects", "-demo")):
        os.makedirs(d)
    for name, body in (("claude", FAKE_CLAUDE), ("gh", FAKE_GH)):
        p = os.path.join(BASE, "bin", name)
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o755)

    for name, mins, n, dirty, _ in CLONED:
        make_repo(os.path.join(code, name), mins, n, f"git@github.com:{OWNER}/{name}.git", dirty)
    for name, mins, n, dirty, _ in LOCAL_ONLY:
        make_repo(os.path.join(code, name), mins, n, None, dirty)
    sh(["git", "worktree", "add", "-q", "-b", "map-view", os.path.join(code, "trail-planner-map-view")],
       os.path.join(code, "trail-planner"))

    # Other: plain folders and someone else's clone, some of them old
    for name, days in (("old-experiments", 210), ("meeting-notes-export", 40), ("holiday-photos-2022", 330)):
        d = os.path.join(scratch, name)
        os.makedirs(d)
        t = time.time() - days * 86400
        os.utime(d, (t, t))
    make_repo(os.path.join(scratch, "forked-linter"), 150 * 24 * 60, 8, "git@github.com:acme-oss/linter.git", dirty=1)

    repos = []
    for name, mins, _, _, _ in CLONED:
        repos.append({"name": name, "description": DESCRIPTIONS[name], "visibility": "PRIVATE", "isArchived": False,
                      "pushedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - mins * 60)),
                      "pullRequests": {"totalCount": PRS.get(name, 0)}, "issues": {"totalCount": 0}})
    for name, mins, desc in GITHUB_ONLY:
        repos.append({"name": name, "description": desc, "visibility": "PUBLIC", "isArchived": False,
                      "pushedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - mins * 60)),
                      "pullRequests": {"totalCount": 0}, "issues": {"totalCount": 0}})
    with open(os.path.join(BASE, "gh-repos.json"), "w") as f:
        json.dump(repos, f)

    tags = {}
    for name, _, _, _, tag in CLONED + LOCAL_ONLY:
        tags[name] = [tag]
    with open(os.path.join(BASE, "config"), "w") as f:
        f.write(f'owners = ["{OWNER}"]\nscan_roots = ["{code}", "{scratch}"]\npinned = []\n[tags]\n' +
                "".join(f"{k} = {json.dumps(v)}\n" for k, v in tags.items()))

    # Claude sessions: one working, one idle for two days, one whose process has exited, one past
    me, ppid = os.getpid(), os.getppid()

    def proc_start(pid):
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[19]
    now_ms = int(time.time() * 1000)
    reg = [
        {"pid": me, "sessionId": "aaaa1111-0000", "jobId": "a1b2c3d4", "kind": "bg", "status": "busy",
         "name": "Import recipes from CSV", "cwd": os.path.join(code, "recipe-box"), "procStart": proc_start(me),
         "startedAt": now_ms - 40 * 60000, "updatedAt": now_ms - 20000},
        {"pid": ppid, "sessionId": "bbbb2222-0000", "jobId": "e5f6a7b8", "kind": "bg", "status": "idle",
         "name": "Overnight test run", "cwd": os.path.join(code, "budget-tracker"), "procStart": proc_start(ppid),
         "startedAt": now_ms - 3 * 86400000, "updatedAt": now_ms - 2 * 86400000 - 3600000},
        {"pid": 999999, "sessionId": "cccc3333-0000", "jobId": "c9d0e1f2", "kind": "bg", "status": "idle",
         "name": "Fix flaky login test", "cwd": os.path.join(code, "weather-cli"), "procStart": "1",
         "startedAt": now_ms - 5 * 86400000, "updatedAt": now_ms - 4 * 86400000},
    ]
    for r in reg:
        with open(os.path.join(BASE, ".claude", "sessions", f"{r['pid']}.json"), "w") as f:
            json.dump(r, f)
    for sid, title, cwd, hours in (("dddd4444-0000", "Add dark mode", "trail-planner", 30),
                                   ("eeee5555-0000", "Tidy the README", "dotfiles", 200)):
        path = os.path.join(BASE, ".claude", "projects", "-demo", sid + ".jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": title}) + "\n")
            f.write(json.dumps({"type": "user", "cwd": os.path.join(code, cwd), "message": {"content": title}}) + "\n")
        t = time.time() - hours * 3600
        os.utime(path, (t, t))


# --- tmux driving -----------------------------------------------------------------------------------------------

SOCK = f"demo-shots-{os.getpid()}"


def tmux(*args):
    return subprocess.run(["tmux", "-L", SOCK] + list(args), capture_output=True, text=True)


def screen_text():
    return tmux("capture-pane", "-t", "t", "-p").stdout


def screen_ansi():
    return tmux("capture-pane", "-t", "t", "-p", "-e").stdout


def wait_for(pred, what, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if pred(screen_text()):
            return
        time.sleep(0.15)
    sys.exit(f"timed out waiting for {what}\n{screen_text()}")


def settle():
    wait_for(lambda s: "+T*" not in s, "reload to settle")
    time.sleep(0.9)


def key(*keys):
    tmux("send-keys", "-t", "t", *keys)


def start():
    env = {"HOME": BASE, "PATH": f"{BASE}/bin:/usr/bin:/bin", "CLAUDE_HUB_CACHE_DIR": f"{BASE}/cache",
           "CLAUDE_HUB_CONFIG": f"{BASE}/config", "CLAUDE_HUB_CLONE_ROOT": f"{BASE}/code",
           "CLAUDE_HUB_NO_AGENTS": "1", "XDG_RUNTIME_DIR": BASE, "DEMO_GH_REPOS": f"{BASE}/gh-repos.json",
           "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8"}
    inner = " ".join(["env"] + [f"{k}={v}" for k, v in env.items()] + [sys.executable, HUB])
    tmux("new-session", "-d", "-s", "t", "-x", str(COLS), "-y", str(ROWS), inner)


# --- ANSI -> HTML -> PNG ---------------------------------------------------------------------------------------

PALETTE = ["#45475a", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#bac2de",
           "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#a6adc8"]
FG, BG = "#cdd6f4", "#1e1e2e"


def color256(n):
    if n < 16:
        return PALETTE[n]
    if n < 232:
        n -= 16
        lv = [0, 95, 135, 175, 215, 255]
        return "#%02x%02x%02x" % (lv[n // 36], lv[(n // 6) % 6], lv[n % 6])
    v = 8 + (n - 232) * 10
    return "#%02x%02x%02x" % (v, v, v)


def ansi_to_html(text):
    state = {"fg": None, "bg": None, "bold": False, "dim": False, "ul": False, "rev": False, "it": False}
    out, pos = [], 0

    def span(chunk):
        if not chunk:
            return
        fg, bg = state["fg"] or FG, state["bg"] or BG
        if state["rev"]:
            fg, bg = bg, fg
        style = f"color:{fg};background:{bg};"
        if state["bold"]:
            style += "font-weight:bold;"
        if state["dim"]:
            style += "opacity:.7;"
        if state["ul"]:
            style += "text-decoration:underline;"
        if state["it"]:
            style += "font-style:italic;"
        out.append(f'<span style="{style}">{html.escape(chunk)}</span>')

    for m in re.finditer(r"\x1b\[([0-9;:]*)m|\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Z0-9]", text):
        span(text[pos:m.start()])
        pos = m.end()
        if m.group(1) is None:
            continue
        codes = [int(c) if c else 0 for c in re.split(r"[;:]", m.group(1))] or [0]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                state.update(fg=None, bg=None, bold=False, dim=False, ul=False, rev=False, it=False)
            elif c == 1:
                state["bold"] = True
            elif c == 2:
                state["dim"] = True
            elif c == 3:
                state["it"] = True
            elif c == 4:
                state["ul"] = True
            elif c == 7:
                state["rev"] = True
            elif c == 22:
                state["bold"] = state["dim"] = False
            elif c == 23:
                state["it"] = False
            elif c == 24:
                state["ul"] = False
            elif c == 27:
                state["rev"] = False
            elif 30 <= c <= 37:
                state["fg"] = PALETTE[c - 30]
            elif 90 <= c <= 97:
                state["fg"] = PALETTE[c - 90 + 8]
            elif 40 <= c <= 47:
                state["bg"] = PALETTE[c - 40]
            elif 100 <= c <= 107:
                state["bg"] = PALETTE[c - 100 + 8]
            elif c == 39:
                state["fg"] = None
            elif c == 49:
                state["bg"] = None
            elif c in (38, 48):
                key_ = "fg" if c == 38 else "bg"
                if i + 2 < len(codes) and codes[i + 1] == 5:
                    state[key_] = color256(codes[i + 2])
                    i += 2
                elif i + 4 < len(codes) and codes[i + 1] == 2:
                    state[key_] = "#%02x%02x%02x" % tuple(codes[i + 2:i + 5])
                    i += 4
            i += 1
    span(text[pos:])
    return "".join(out)


def render(ansi, name):
    lines = ansi.rstrip("\n").split("\n")
    body = "\n".join(ansi_to_html(l) for l in lines)
    page = (f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:{BG};}}'
            f'pre{{margin:0;padding:24px;font:15px/1.25 {FONT};color:{FG};background:{BG};width:max-content}}'
            f'</style><pre>{body}</pre>')
    tmp = os.path.join(BASE, f"{name}.html")
    with open(tmp, "w") as f:
        f.write(page)
    png = os.path.join(OUT, f"{name}.png")
    sh(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
        f"--screenshot={png}", "--window-size=1700,900", "--force-device-scale-factor=1", f"file://{tmp}"], check=False)
    sh(["magick", png, "-trim", "+repage", "-bordercolor", BG, "-border", "0", png])


def main():
    for tool in ("tmux", "fzf", "git", "chromium", "magick"):
        if not shutil.which(tool):
            sys.exit(f"missing {tool}")
    os.makedirs(OUT, exist_ok=True)
    build()
    start()
    try:
        wait_for(lambda s: "repo>" in s and "recipe-box" in s, "picker")
        lock = os.path.join(BASE, "cache", "refresh.lock")
        end = time.time() + 30
        while os.path.exists(lock) and time.time() < end:
            time.sleep(0.2)
        settle()
        wait_for(lambda s: "dashboard" in s and "streak" in s, "dashboard preview")
        time.sleep(0.5)
        render(screen_ansi(), "projects-dashboard")

        key("Down")
        wait_for(lambda s: "recipe-box" in s.split("│", 1)[-1] and "last commit" not in s or "Recipe manager" in s,
                 "project preview")
        time.sleep(1.2)
        render(screen_ansi(), "project-preview")

        key("Up")                       # back to the first row, so the next tab opens on its summary row
        settle()
        key("M-2")
        wait_for(lambda s: "[Other" in s and "stale" in s, "Other tab")
        settle()
        wait_for(lambda s: "hidden = " in s, "stale dashboard")
        render(screen_ansi(), "other-tab")

        key("M-3")
        wait_for(lambda s: "[Sessions" in s and "needs you" in s, "Sessions tab")
        settle()
        wait_for(lambda s: "to deal with" in s, "needs-you dashboard")
        render(screen_ansi(), "sessions-tab")
    finally:
        tmux("kill-server")
    print("wrote", ", ".join(sorted(os.listdir(OUT))))


if __name__ == "__main__":
    main()
