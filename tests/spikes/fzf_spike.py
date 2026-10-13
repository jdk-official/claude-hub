#!/usr/bin/env python3
"""Q1 spike: verify the fzf mechanisms iteration 2 relies on, against the installed fzf.
Drives real fzf in a tmux pane and prints PASS/FAIL per mechanism. Run: python3 tests/spikes/fzf_spike.py"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

SOCK = f"fzfspike-{os.getpid()}"
TMP = tempfile.mkdtemp(prefix="fzfspike-")
RESULTS = []


def tmux(*a):
    return subprocess.run(["tmux", "-L", SOCK] + list(a), capture_output=True, text=True).stdout


def start(cmd, cols=100, rows=24):
    tmux("kill-server")
    tmux("new-session", "-d", "-s", "s", "-x", str(cols), "-y", str(rows), f"{cmd}; echo SPIKE_EXIT=$?; sleep 20")
    time.sleep(0.8)


def screen():
    return tmux("capture-pane", "-t", "s", "-p")


def keys(*k, literal=False):
    tmux("send-keys", "-t", "s", *(["-l"] if literal else []), *k)
    time.sleep(0.3)


def wait(pred, timeout=4.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    return False


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def ready(port, tries=30):
    for _ in range(tries):
        try:
            state(port)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def post(port, action):
    req = urllib.request.Request(f"http://127.0.0.1:{port}", data=action.encode(), method="POST")
    return urllib.request.urlopen(req, timeout=3).read()


def state(port):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/?limit=0", timeout=3).read())


def record(name, ok, note=""):
    RESULTS.append((name, ok, note))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {note}")


ITEMS = os.path.join(TMP, "items.tsv")
ITEMS2 = os.path.join(TMP, "items2.tsv")
with open(ITEMS, "w") as f:   # name \t display (name + columns) \t path
    f.write("alpha\talpha   main clean   today\t/p/alpha\n"
            "beta\tbeta    main *2      today\t/p/beta\n"
            "gamma\tgamma   release     today\t/p/gamma\n"
            "delta\tdelta   main clean   3d\t/p/delta\n")
with open(ITEMS2, "w") as f:  # a new row at the top and one changed row
    f.write("zeta\tzeta    main clean   today\t/p/zeta\n"
            "alpha\talpha   main clean   today\t/p/alpha\n"
            "beta\tbeta    main *2      today\t/p/beta\n"
            "gamma\tgamma   release *1   today\t/p/gamma\n"
            "delta\tdelta   main clean   3d\t/p/delta\n")
BASE = f"cat {ITEMS} | fzf --delimiter '\\t' --with-nth 2"

# 1. header above the prompt
start(BASE + " --header 'STATS HEADER' --header-first --layout reverse")
s = screen().splitlines()
hi = next((i for i, l in enumerate(s) if "STATS HEADER" in l), -1)
pi = next((i for i, l in enumerate(s) if l.startswith(">")), -1)
record("--header-first puts header above the prompt (reverse layout)", 0 <= hi < pi, f"header row {hi}, prompt row {pi}")

# 2. footer
start(BASE + " --footer 'FOOTER KEYS' --layout reverse")
record("--footer renders", "FOOTER KEYS" in screen())

# 3. naive attempt: --with-nth 2 --nth 1 over one tab-free display field does NOT restrict search
start(BASE + " --nth 1 --layout reverse")
keys("clean", literal=True)
t = screen()
naive_restricts = "alpha" not in t and "delta" not in t
record("(finding) --with-nth 2 --nth 1 does not restrict search to the name",
       not naive_restricts, "display columns are still searched" if not naive_restricts else "unexpectedly restricted")

# 4. working approach: show fields 1,2 (name, columns) and search field 1 only
TWO = f"cat {ITEMS} | fzf --delimiter '\\t' --with-nth 1,2 --nth 1 --layout reverse"
start(TWO)
keys("clean", literal=True)
t = screen()
record("--with-nth 1,2 --nth 1: a query matching only a column matches nothing",
       "alpha" not in t and "delta" not in t and "0/4" in t)
start(TWO)
keys("gam", literal=True)
t = screen()
record("--with-nth 1,2 --nth 1: a name query finds the row", "gamma" in t and "alpha" not in t)

# 5. reload via --listen keeps cursor and query with --track --id-nth
port = free_port()
start(BASE + f" --listen {port} --track --id-nth 1 --layout reverse")
keys("Down", "Down")       # cursor on gamma (rows: alpha, beta, gamma, delta)
try:
    assert ready(port), "fzf --listen server did not come up"
    before = state(port)["current"]["text"]
    post(port, f"reload(cat {ITEMS2})")
    time.sleep(0.6)
    after = state(port)["current"]["text"]
    record("reload via --listen with --track --id-nth keeps the highlighted row",
           "gamma" in before and "gamma" in after, f"before={before.split()[0]} after={after.split()[0]}")
    rows = [l for l in screen().splitlines() if "zeta" in l]
    record("reloaded list shows the new row", bool(rows))
except Exception as e:  # pragma: no cover
    record("reload via --listen", False, repr(e))

# 6. reload preserves the query
port = free_port()
start(BASE + f" --listen {port} --track --id-nth 1 --layout reverse")
keys("a", literal=True)
try:
    assert ready(port), "fzf --listen server did not come up"
    post(port, f"reload(cat {ITEMS2})")
    time.sleep(0.6)
    st = state(port)
    record("reload preserves the typed query", st.get("query") == "a", f"query={st.get('query')!r}")
except Exception as e:  # pragma: no cover
    record("reload preserves query", False, repr(e))

# 7. change-header from outside
port = free_port()
start(BASE + f" --listen {port} --header 'OLD HEADER' --header-first --layout reverse")
try:
    assert ready(port), "fzf --listen server did not come up"
    post(port, "change-header(NEW HEADER streak 2d)")
    record("change-header updates the header in place", wait(lambda: "NEW HEADER" in screen()))
except Exception as e:  # pragma: no cover
    record("change-header", False, repr(e))

# 8. become() replaces fzf with a command run in the selected row's directory
out = os.path.join(TMP, "became.txt")
start(BASE + f" --bind 'enter:become(printf \"%s\\n\" {{3}} > {out})' --layout reverse")
keys("Down", "Enter")
time.sleep(0.5)
got = open(out).read().strip() if os.path.exists(out) else ""
record("become() runs with the selected row's field", got == "/p/beta", f"got={got!r}")

# 9. --expect still returns the key (current launch mechanism)
start(f"cat {ITEMS} | fzf --delimiter '\\t' --with-nth 2 --expect ctrl-l --layout reverse > {out}; cat {out}")
keys("C-l")
time.sleep(0.5)
record("--expect returns the pressed key", "ctrl-l" in screen())

# 10. fzf version
ver = subprocess.run(["fzf", "--version"], capture_output=True, text=True).stdout.split()[0]
print(f"\nfzf {ver}: {sum(1 for _, ok, _ in RESULTS if ok)}/{len(RESULTS)} mechanisms verified")
tmux("kill-server")
sys.exit(0 if all(ok for _, ok, _ in RESULTS) else 1)
