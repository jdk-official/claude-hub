"""End-to-end tests: drive the real picker (fzf) in a tmux pane with fake claude/gh on PATH.
Run: python3 -m unittest tests.test_e2e -v   (skipped if tmux or fzf is missing)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = os.path.join(ROOT, "bin", "hub")
HAVE = bool(shutil.which("tmux") and shutil.which("fzf") and shutil.which("git"))

FAKE_CLAUDE = """#!/bin/sh
printf 'cwd=%s\\nargs=%s\\n' "$PWD" "$*" > "$HUB_E2E_OUT"
"""
FAKE_GH = """#!/bin/sh
case "$1 $2" in
  "repo list")
    [ -n "$HUB_E2E_SLEEP" ] && sleep "$HUB_E2E_SLEEP"
    if [ -f "$HUB_E2E_REPOS" ]; then cat "$HUB_E2E_REPOS"; exit 0; fi
    echo "no network" >&2; exit 1 ;;
  "repo clone") mkdir -p "$4"; echo partial > "$4/partial.txt"; exit 1 ;;
  "api rate_limit") [ -n "$HUB_E2E_OFFLINE" ] && exit 1; exit 0 ;;
  "pr list") echo '[{"title":"an open PR"}]'; exit 0 ;;
  "issue list") echo '[]'; exit 0 ;;
  *) exit 1 ;;
esac
"""


def git(args, cwd, env=None):
    e = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    e.update(env or {})
    subprocess.run(["git"] + args, cwd=cwd, env=e, check=True, capture_output=True)


def make_repo(path, files, dirty=False):
    os.makedirs(path)
    git(["init", "-q", "-b", "main"], path)
    for name, text in files.items():
        with open(os.path.join(path, name), "w") as f:
            f.write(text)
    git(["add", "-A"], path)
    now = time.strftime("%Y-%m-%dT12:00:00")
    git(["-c", "user.name=T", "-c", "user.email=jonathan@kyte.me.uk", "commit", "-q", "-m", "first commit"],
        path, env={"GIT_AUTHOR_DATE": now, "GIT_COMMITTER_DATE": now})
    if dirty:
        with open(os.path.join(path, "wip.txt"), "w") as f:
            f.write("x")


@unittest.skipUnless(HAVE, "needs tmux, fzf and git")
class E2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hube2e-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        t = self.tmp
        self.home, self.bin = os.path.join(t, "home"), os.path.join(t, "bin")
        self.root, self.clones = os.path.join(t, "root"), os.path.join(t, "clones")
        self.cache, self.out = os.path.join(t, "cache"), os.path.join(t, "claude.out")
        self.run_dir = os.path.join(t, "run")
        for d in (self.home, self.bin, self.root, self.clones, self.cache, self.run_dir):
            os.makedirs(d)
        for name, body in (("claude", FAKE_CLAUDE), ("gh", FAKE_GH)):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        make_repo(os.path.join(self.root, "alpha"), {"README.md": "# Alpha\nalpha readme line\n"})
        make_repo(os.path.join(self.root, "beta"), {"HANDOVER.md": "# Beta\nbeta handover note\n"}, dirty=True)
        with open(os.path.join(t, "config"), "w") as f:
            f.write(f'owners=["o"]\nscan_roots=["{self.root}"]\n[tags]\nalpha=["work"]\nbeta=["home"]\n')
        with open(os.path.join(self.cache, "repos.json"), "w") as f:
            json.dump({"version": 1, "gh": {"ok": True, "fetched_at": time.time(), "last_attempt": time.time(),
                       "error": "", "repos": [{"name": "remote-only", "owner": "o", "visibility": "PRIVATE",
                                               "description": "remote desc", "isArchived": False,
                                               "pushedAt": "2026-10-01T00:00:00Z"}]}}, f)
        self.sock = f"hube2e-{os.getpid()}-{id(self)}"
        self.addCleanup(self.tmux, "kill-server")

    def tmux(self, *args):
        return subprocess.run(["tmux", "-L", self.sock] + list(args), capture_output=True, text=True)

    def start(self, cols=150, rows=40, argv=(), extra_env=None):
        env = {"HOME": self.home, "PATH": f"{self.bin}:/usr/bin:/bin", "HUB_CACHE_DIR": self.cache,
               "HUB_CONFIG": os.path.join(self.tmp, "config"), "HUB_CLONE_ROOT": self.clones,
               "HUB_E2E_OUT": self.out, "XDG_RUNTIME_DIR": self.run_dir, "HUB_E2E_REPOS": os.path.join(self.tmp, "gh-repos.json"), "TERM": "xterm-256color", "LANG": "C.UTF-8"}
        env.update(extra_env or {})
        inner = " ".join(["env"] + [f"{k}={v}" for k, v in env.items()] + [sys.executable, HUB] + list(argv))
        # keep the pane alive after hub exits so its final message can be read
        r = self.tmux("new-session", "-d", "-s", "t", "-x", str(cols), "-y", str(rows),
                      f"{inner}; echo HUB_EXIT=$?; sleep 30")
        self.assertEqual(r.returncode, 0, r.stderr)

    def screen(self):
        return self.tmux("capture-pane", "-t", "t", "-p").stdout

    def wait_for(self, pred, what, timeout=6.0):
        end = time.time() + timeout
        while time.time() < end:
            if pred():
                return
            time.sleep(0.1)
        self.fail(f"timed out waiting for {what}\n--- screen ---\n{self.screen()}")

    def ready(self):
        self.wait_for(lambda: "repo>" in self.screen() and "alpha" in self.screen(), "picker")

    def type(self, text):
        self.tmux("send-keys", "-t", "t", "-l", text)

    def key(self, *keys):
        self.tmux("send-keys", "-t", "t", *keys)

    def claude_call(self):
        self.wait_for(lambda: os.path.exists(self.out), "claude to be launched")
        with open(self.out) as f:
            return dict(l.split("=", 1) for l in f.read().splitlines())

    # --- launch ---------------------------------------------------------
    def test_enter_starts_new_session_in_repo(self):
        self.start()
        self.ready()
        self.type("alpha")
        self.wait_for(lambda: "alpha readme line" in self.screen(), "alpha preview")
        self.key("Enter")
        call = self.claude_call()
        self.assertEqual(os.path.realpath(call["cwd"]), os.path.realpath(os.path.join(self.root, "alpha")))
        self.assertEqual(call["args"], "")

    def test_launch_adds_the_dashboard_mod_like_the_shell_function(self):
        mod = os.path.join(self.home, ".claude", "mods", "project-dashboard")
        os.makedirs(mod)
        self.start()
        self.ready()
        self.type("alpha")
        self.wait_for(lambda: "alpha readme line" in self.screen(), "alpha preview")
        self.key("C-l")
        self.assertEqual(self.claude_call()["args"], f"--plugin-dir {mod} --continue")

    def test_ctrl_l_resumes(self):
        self.start()
        self.ready()
        self.type("beta")
        self.wait_for(lambda: "beta handover note" in self.screen(), "beta preview")
        self.key("C-l")
        call = self.claude_call()
        self.assertTrue(call["cwd"].endswith("/beta"))
        self.assertEqual(call["args"], "--continue")

    def test_escape_exits_without_launching(self):
        self.start()
        self.ready()
        self.key("Escape")
        time.sleep(0.8)
        self.assertFalse(os.path.exists(self.out))

    # --- layout ---------------------------------------------------------
    def box_column(self):
        for line in self.screen().splitlines():
            if "╭" in line:
                return line.index("╭")
        return None

    def test_wide_window_puts_preview_beside_list(self):
        self.start(cols=150)
        self.ready()
        col = self.box_column()
        self.assertIsNotNone(col)
        self.assertGreater(col, 40)

    def test_narrow_window_puts_preview_below_list(self):
        self.start(cols=60, rows=40)
        self.wait_for(lambda: "repo>" in self.screen(), "picker")
        time.sleep(0.5)
        col = self.box_column()
        self.assertIsNotNone(col, self.screen())
        self.assertLess(col, 3, "preview box should start at the left edge when stacked\n" + self.screen())

    # --- content --------------------------------------------------------
    def test_typing_filters_the_list(self):
        self.start()
        self.ready()
        self.type("bet")
        self.wait_for(lambda: "beta handover note" in self.screen(), "beta preview")
        self.assertNotIn("alpha readme", self.screen())

    def test_dirty_marker_and_state_shown(self):
        self.start()
        self.ready()
        screen = self.screen()
        beta = next(l for l in screen.splitlines() if l.lstrip(" ▌").startswith("beta"))
        self.assertIn("●1", beta)

    def test_github_only_repo_is_listed_with_cloud_marker(self):
        self.start()
        self.ready()
        row = next(l for l in self.screen().splitlines() if "remote-only" in l)
        self.assertIn("☁", row)

    def test_home_row_shows_dashboard(self):
        self.start()
        self.ready()
        self.wait_for(lambda: "dashboard" in self.screen(), "dashboard preview")

    # --- clone ----------------------------------------------------------
    def test_clone_declined_leaves_nothing(self):
        self.start()
        self.ready()
        self.type("remote-only")
        self.wait_for(lambda: "not cloned" in self.screen(), "remote preview")
        self.key("Enter")
        self.wait_for(lambda: "Clone o/remote-only" in self.screen(), "clone prompt")
        self.key("n", "Enter")
        time.sleep(0.5)
        self.assertEqual(os.listdir(self.clones), [])
        self.assertFalse(os.path.exists(self.out))

    def test_clone_failure_cleans_up_partial_directory(self):
        self.start()
        self.ready()
        self.type("remote-only")
        self.wait_for(lambda: "not cloned" in self.screen(), "remote preview")
        self.key("Enter")
        self.wait_for(lambda: "Clone o/remote-only" in self.screen(), "clone prompt")
        self.key("y", "Enter")
        self.wait_for(lambda: "nothing was left on disk" in self.screen(), "failure message")
        self.assertEqual(os.listdir(self.clones), [])

    def test_clone_refused_when_github_unreachable(self):  # FR-27
        with open(os.path.join(self.cache, "repos.json")) as f:
            c = json.load(f)
        c["gh"]["ok"] = False
        with open(os.path.join(self.cache, "repos.json"), "w") as f:
            json.dump(c, f)
        self.start(extra_env={"HUB_E2E_OFFLINE": "1"})
        self.ready()
        self.type("remote-only")
        self.wait_for(lambda: "not cloned" in self.screen(), "remote preview")
        self.key("Enter")
        self.wait_for(lambda: "unreachable" in self.screen(), "refusal message")
        self.assertNotIn("[y/N]", self.screen())
        self.assertEqual(os.listdir(self.clones), [])


    # --- iteration 2 ----------------------------------------------------
    def gh_repos_file(self, *names):
        with open(os.path.join(self.tmp, "gh-repos.json"), "w") as f:
            json.dump([{"name": n, "description": "d", "visibility": "PRIVATE", "isArchived": False,
                        "pushedAt": "2026-10-12T00:00:00Z"} for n in names], f)

    def prompt_row(self):
        return next(i for i, l in enumerate(self.screen().splitlines()) if l.startswith("repo>"))

    def test_header_is_above_the_prompt_and_footer_lists_keys(self):  # FR-35, AC-26
        self.start()
        self.ready()
        lines = self.screen().splitlines()
        header_row = next(i for i, l in enumerate(lines) if "GitHub:" in l)
        self.assertLess(header_row, self.prompt_row())
        footer = "\n".join(lines)
        for key in ("enter", "ctrl-l", "ctrl-r", "ctrl-t", "esc"):
            self.assertIn(key, footer)

    def test_query_matches_name_not_branch_or_age(self):  # FR-34, AC-25
        self.start()
        self.ready()
        self.type("main")           # every repo is on branch main, none is named main
        self.wait_for(lambda: "0/" in self.screen(), "no matches for a branch-only query")
        self.assertNotIn("alpha readme", self.screen())

    def test_query_matches_tags(self):  # FR-34
        self.start()
        self.ready()
        self.type("home")
        self.wait_for(lambda: "beta handover note" in self.screen(), "beta via its tag")
        self.assertNotIn("alpha readme", self.screen())

    def list_rows(self):
        """Names shown in the list pane (left of the preview box), without the preview text."""
        rows = []
        for line in self.screen().splitlines():
            left = line.split("│")[0]
            parts = left.lstrip(" ▌").split()
            if parts:
                rows.append(parts[0])
        return rows

    def test_ctrl_t_cycles_tag_filter(self):  # FR-15
        self.start()
        self.ready()
        self.key("C-t")
        self.wait_for(lambda: "tag filter: #home" in self.screen() and "1/1" in self.screen() and "+T*" not in self.screen(),
                      "first tag applied and settled")
        time.sleep(0.5)   # a keypress while fzf is still finishing the previous reload is ignored
        self.assertIn("beta", self.list_rows())
        self.assertNotIn("alpha", self.list_rows())
        self.key("C-t")
        self.wait_for(lambda: "tag filter: #work" in self.screen() and "1/1" in self.screen() and "+T*" not in self.screen(),
                      "second tag applied and settled")
        time.sleep(0.5)
        self.assertIn("alpha", self.list_rows())
        self.assertNotIn("beta", self.list_rows())
        self.key("C-t")
        self.wait_for(lambda: "tag filter:" not in self.screen() and "4/4" in self.screen(), "filter cleared")

    def test_background_refresh_updates_list_in_place_and_keeps_query(self):  # FR-2, AC-2
        self.gh_repos_file("alphanew", "remote-only")
        self.start(extra_env={"HUB_E2E_SLEEP": "2"})
        self.ready()
        self.type("al")
        self.wait_for(lambda: "alphanew" not in self.screen(), "pre-refresh state")
        self.wait_for(lambda: "alphanew" in self.screen(), "new repo to appear without a restart", 12)
        self.assertIn("repo> al", self.screen())

    def test_ctrl_r_refreshes_on_demand(self):  # FR-3
        self.start()
        self.ready()
        self.assertNotIn("alphanew", self.screen())
        self.gh_repos_file("alphanew", "remote-only")
        self.key("C-r")
        self.wait_for(lambda: "alphanew" in self.screen(), "repo to appear after ctrl-r", 12)

    def session_dirs(self):
        return [d for d in os.listdir(self.run_dir) if d.startswith("hub-")]

    def test_viewing_projects_does_not_reorder_the_list(self):
        self.gh_repos_file("remote-only", "another")
        self.start()
        self.ready()
        self.wait_for(lambda: "another" in self.screen(), "refresh with both repos", 10)
        time.sleep(0.5)
        order = [r for r in self.list_rows() if r in ("alpha", "beta", "remote-only", "another", "~")]
        for _ in range(len(order)):          # highlight every project, which triggers the lazy PR fetch
            self.key("Down")
            time.sleep(0.4)
        time.sleep(1.5)                      # let any (unwanted) reload settle
        after = [r for r in self.list_rows() if r in ("alpha", "beta", "remote-only", "another", "~")]
        self.assertEqual(after, order, "viewing projects must not change their order")

    def test_session_socket_exists_during_session_and_is_cleaned_up(self):
        self.start()
        self.ready()
        dirs = self.session_dirs()
        self.assertEqual(len(dirs), 1)
        sess = os.path.join(self.run_dir, dirs[0])
        self.assertEqual(os.stat(sess).st_mode & 0o777, 0o700)
        self.assertTrue(os.path.exists(os.path.join(sess, "fzf.sock")))
        self.key("Escape")
        self.wait_for(lambda: self.session_dirs() == [], "session dir removal")

    def test_ctrl_r_does_not_block_input_while_refresh_runs(self):  # NFR-3
        self.gh_repos_file("remote-only")
        self.start(extra_env={"HUB_E2E_SLEEP": "3"})
        self.ready()
        lock = os.path.join(self.cache, "refresh.lock")
        self.wait_for(lambda: not os.path.exists(lock), "startup refresh to finish", 10)
        self.gh_repos_file("alphanew", "remote-only")
        self.key("C-r")
        self.type("al")
        # typing must show up while the (3 s) refresh is still running
        self.wait_for(lambda: "refreshing> al" in self.screen(), "typed text visible during refresh", 1.5)
        self.wait_for(lambda: "alphanew" in self.screen() and "repo> al" in self.screen(),
                      "refreshed list and restored prompt", 12)

    def test_unusable_cache_dir_does_not_crash_the_picker(self):
        blocker = os.path.join(self.tmp, "blocker")
        open(blocker, "w").close()
        bad = os.path.join(blocker, "sub")
        env = {"HUB_CACHE_DIR": bad}
        self.start(extra_env=env)
        self.wait_for(lambda: "repo>" in self.screen(), "picker with unusable cache dir")
        self.assertNotIn("Traceback", self.screen())
        self.key("Escape")
        self.wait_for(lambda: "HUB_EXIT=0" in self.screen(), "clean exit")

    # --- refresh --------------------------------------------------------
    def test_failed_background_refresh_keeps_cached_github_rows(self):
        self.start()
        self.ready()
        self.key("Escape")
        lock = os.path.join(self.cache, "refresh.lock")
        self.wait_for(lambda: not os.path.exists(lock), "background refresh to finish", 10)
        self.tmux("kill-server")
        self.start()
        self.ready()
        self.assertIn("remote-only", self.screen())
        self.assertNotIn("local only", self.screen().split("repo>")[1].split("alpha")[0])


if __name__ == "__main__":
    unittest.main()
