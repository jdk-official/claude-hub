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
HUB = os.path.join(ROOT, "bin", "claude-hub")
HAVE = bool(shutil.which("tmux") and shutil.which("fzf") and shutil.which("git"))

FAKE_CLAUDE = """#!/bin/sh
printf 'cwd=%s\\nargs=%s\\n' "$PWD" "$*" > "$CLAUDE_HUB_E2E_OUT"
"""
FAKE_GH = """#!/bin/sh
case "$1 $2" in
  "repo list")
    [ -n "$CLAUDE_HUB_E2E_SLEEP" ] && sleep "$CLAUDE_HUB_E2E_SLEEP"
    if [ -f "$CLAUDE_HUB_E2E_REPOS" ]; then cat "$CLAUDE_HUB_E2E_REPOS"; exit 0; fi
    echo "no network" >&2; exit 1 ;;
  "repo clone") mkdir -p "$4"; echo partial > "$4/partial.txt"; exit 1 ;;
  "api rate_limit") [ -n "$CLAUDE_HUB_E2E_OFFLINE" ] && exit 1; exit 0 ;;
  "pr list") echo '[{"title":"an open PR"}]'; exit 0 ;;
  "issue list") echo '[]'; exit 0 ;;
  *) exit 1 ;;
esac
"""


os.environ.setdefault("CLAUDE_HUB_NO_AGENTS", "1")   # never ask a real or fake claude to list sessions


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
    git(["-c", "user.name=T", "-c", "user.email=dev@example.com", "commit", "-q", "-m", "first commit"],
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
        env = {"HOME": self.home, "PATH": f"{self.bin}:/usr/bin:/bin", "CLAUDE_HUB_CACHE_DIR": self.cache,
               "CLAUDE_HUB_CONFIG": os.path.join(self.tmp, "config"), "CLAUDE_HUB_CLONE_ROOT": self.clones,
               "CLAUDE_HUB_NO_AGENTS": "1", "CLAUDE_HUB_E2E_OUT": self.out, "XDG_RUNTIME_DIR": self.run_dir, "CLAUDE_HUB_E2E_REPOS": os.path.join(self.tmp, "gh-repos.json"), "TERM": "xterm-256color", "LANG": "C.UTF-8"}
        env.update(extra_env or {})
        inner = " ".join(["env"] + [f"{k}={v}" for k, v in env.items()] + [sys.executable, HUB] + list(argv))
        # keep the pane alive after claude-hub exits so its final message can be read
        for attempt in range(3):         # tmux occasionally fails to start a server while another is exiting
            r = self.tmux("new-session", "-d", "-s", "t", "-x", str(cols), "-y", str(rows),
                          f"{inner}; echo HUB_EXIT=$?; sleep 30")
            if r.returncode == 0:
                break
            time.sleep(0.4)
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

    def quiet(self):
        """Wait for the startup background refresh to finish and its reload to land. A key pressed while fzf
        re-finds the tracked row is discarded, which is correct behaviour but makes timing-sensitive tests flaky."""
        lock = os.path.join(self.cache, "refresh.lock")
        self.wait_for(lambda: not os.path.exists(lock), "background refresh to finish", 12)
        time.sleep(0.8)
        self.wait_for(lambda: "+T*" not in self.screen(), "reload to settle", 6)

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

    def test_launch_adds_no_plugin_dir_even_if_an_old_mod_directory_exists(self):
        os.makedirs(os.path.join(self.home, ".claude", "mods", "project-dashboard"))
        self.start()
        self.ready()
        self.type("alpha")
        self.wait_for(lambda: "alpha readme line" in self.screen(), "alpha preview")
        self.key("Enter")
        self.assertEqual(self.claude_call()["args"], "")

    def seed_past_session(self, project, sid="aaaabbbb-1111-2222-3333-444455556666", title="Fix beta bug"):
        d = os.path.join(self.home, ".claude", "projects", "-seeded")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "w") as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": title}) + "\n")
            f.write(json.dumps({"type": "user", "cwd": project, "message": {"content": "please fix the bug"}}) + "\n")
        return sid

    def test_ctrl_l_resumes_the_exact_session_by_id(self):
        sid = self.seed_past_session(os.path.join(self.root, "beta"))
        self.start()
        self.ready()
        self.quiet()
        self.type("beta")
        self.wait_for(lambda: "ctrl-l resumes: Fix beta bug" in self.screen(), "preview names what ctrl-l will do")
        self.settle()
        self.key("C-l")
        call = self.claude_call()
        self.assertTrue(call["cwd"].endswith("/beta"))
        self.assertEqual(call["args"], f"--resume {sid}")        # never --continue

    def test_ctrl_l_with_no_history_starts_a_new_session(self):
        self.start()
        self.ready()
        self.quiet()
        self.type("alpha")
        self.wait_for(lambda: "alpha readme line" in self.screen(), "alpha preview")
        self.settle()
        self.key("C-l")
        call = self.claude_call()
        self.assertTrue(call["cwd"].endswith("/alpha"))
        self.assertEqual(call["args"], "")

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
        beta = next(l for l in screen.splitlines() if l.lstrip(" ▌").startswith("⌂ beta"))
        self.assertIn("●1", beta)

    def test_github_only_repo_is_listed_with_cloud_marker(self):
        self.start()
        self.ready()
        row = next(l for l in self.screen().splitlines() if "remote-only" in l)
        self.assertIn("◌", row)

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
        self.start(extra_env={"CLAUDE_HUB_E2E_OFFLINE": "1"})
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

    def config_top(self, line):
        """Top-level TOML keys must come before the [tags] table."""
        path = os.path.join(self.tmp, "config")
        with open(path) as f:
            body = f.read()
        with open(path, "w") as f:
            f.write(line + "\n" + body)

    def prompt_row(self):
        return next(i for i, l in enumerate(self.screen().splitlines()) if l.startswith("repo>"))

    def test_header_is_above_the_prompt_and_footer_lists_keys(self):  # FR-35, AC-26
        self.start()
        self.ready()
        lines = self.screen().splitlines()
        header_row = next(i for i, l in enumerate(lines) if l.lstrip().startswith("◂"))   # the tab bar
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
            if parts and parts[0] in ("◆", "⌂", "◌", "◇", "▫", "↳"):    # the leading source glyph
                parts = parts[1:]
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
        self.start(extra_env={"CLAUDE_HUB_E2E_SLEEP": "2"})
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
        return [d for d in os.listdir(self.run_dir) if d.startswith("claude-hub-")]

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
        self.start(extra_env={"CLAUDE_HUB_E2E_SLEEP": "3"})
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
        env = {"CLAUDE_HUB_CACHE_DIR": bad}
        self.start(extra_env=env)
        self.wait_for(lambda: "repo>" in self.screen(), "picker with unusable cache dir")
        self.assertNotIn("Traceback", self.screen())
        self.key("Escape")
        self.wait_for(lambda: "HUB_EXIT=0" in self.screen(), "clean exit")


    # --- sessions -------------------------------------------------------
    def seed_sessions(self):
        """A detached background session, a past session with a real directory, and a stale entry."""
        cdir = os.path.join(self.home, ".claude")
        os.makedirs(os.path.join(cdir, "sessions"))
        os.makedirs(os.path.join(cdir, "projects", "-proj"))
        me = os.getpid()
        with open(f"/proc/{me}/stat") as f:
            start = f.read().rsplit(")", 1)[1].split()[19]
        reg = [
            {"pid": me, "sessionId": "11111111-aaaa", "jobId": "ab12cd34", "kind": "bg", "status": "idle",
             "name": "Overnight build", "cwd": self.root, "procStart": start, "startedAt": 1_000, "updatedAt": 2_000},
            {"pid": 999999, "sessionId": "33333333-cccc", "jobId": "ef56ab78", "kind": "bg", "status": "idle",
             "name": "Dead session", "cwd": self.root, "procStart": "1", "startedAt": 1_000, "updatedAt": 2_000},
        ]
        for r in reg:
            with open(os.path.join(cdir, "sessions", f"{r['pid']}.json"), "w") as f:
                json.dump(r, f)
        self.past_cwd = os.path.join(self.tmp, "past-project")
        os.makedirs(self.past_cwd)
        with open(os.path.join(cdir, "projects", "-proj", "22222222-bbbb.jsonl"), "w") as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": "Fix the login bug"}) + "\n")
            f.write(json.dumps({"type": "user", "cwd": self.past_cwd, "message": {"content": "login is broken"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "found it"}]}}) + "\n")
        self.stale_file = os.path.join(cdir, "sessions", "999999.json")

    def settle(self):
        """Wait until fzf has finished its reload (a keypress during tracking is ignored)."""
        self.wait_for(lambda: "+T*" not in self.screen(), "reload to settle", 6)
        time.sleep(0.3)

    def open_sessions_view(self):
        self.seed_sessions()
        self.start()
        self.ready()
        self.quiet()
        self.key("M-3")        # alt-5: jump straight to the Sessions tab
        self.wait_for(lambda: "session>" in self.screen() and "Overnight build" in self.screen(),
                      "sessions view", 8)
        self.settle()

    def test_sessions_tab_has_a_glyph_key(self):
        self.open_sessions_view()
        screen = self.screen()
        for word in ("▶ working", "◉ attached", "○ detached", "▣ terminal", "◈ headless", "⚠ orphan", "✗ stale", "· past"):
            self.assertIn(word, screen)
        self.settle()
        self.key("M-1")
        self.wait_for(lambda: "repo>" in self.screen() and "[Projects" in self.screen(), "back to All", 8)
        self.assertNotIn("◈ headless", self.screen().split("repo>")[0])     # the key belongs to the Sessions tab

    def test_sessions_tab_and_back_to_all(self):
        self.open_sessions_view()
        screen = self.screen()
        self.assertIn("Fix the login bug", screen)
        self.assertIn("Dead session", screen)
        self.assertIn("sessions:", screen)            # the summary line is in the header
        self.assertIn("[Sessions", screen)            # and the tab bar marks the current tab
        self.assertIn("detached", screen)
        self.assertIn("stale", screen)
        self.assertIn("resumable", screen)
        self.settle()
        self.key("M-1")
        self.wait_for(lambda: "repo>" in self.screen() and "beta" in self.screen(), "back to All", 8)
        self.assertIn("[Projects", self.screen())
        self.wait_for(lambda: "~ dashboard" in self.screen(), "home preview replaces the sessions preview", 8)
        self.assertNotIn("Overnight build", self.screen())

    def test_sessions_tab_leads_with_a_needs_you_row_and_its_dashboard(self):
        self.open_sessions_view()
        rows = [l.split("│")[0] for l in self.screen().splitlines()]
        self.assertTrue(any("needs you  2" in r for r in rows), rows)       # the detached-idle and the stale one
        self.wait_for(lambda: "to deal with" in self.screen() and "ctrl-x removes the entry" in self.screen(),
                      "needs-you dashboard in the preview", 8)
        self.assertLess(next(i for i, r in enumerate(rows) if "needs you" in r),
                        next(i for i, r in enumerate(rows) if "Overnight build" in r))
        self.settle()
        self.key("Enter")                                  # a summary row is informational: Enter does nothing
        time.sleep(0.8)
        self.assertFalse(os.path.exists(self.out))
        self.assertIn("session>", self.screen())

    def test_other_tab_leads_with_a_stale_row_listing_old_folders(self):
        old = os.path.join(self.root, "old-folder")
        os.makedirs(old)
        year_ago = time.time() - 200 * 86400
        os.utime(old, (year_ago, year_ago))
        new = os.path.join(self.root, "new-folder")
        os.makedirs(new)
        self.start()
        self.ready()
        self.quiet()
        self.key("M-2")
        self.wait_for(lambda: "[Other" in self.screen() and "stale  1" in self.screen(), "stale summary row", 8)
        self.wait_for(lambda: "old-folder" in self.screen().split("│", 1)[1] and "hidden = " in self.screen(),
                      "stale dashboard in the preview", 8)
        self.assertNotIn("new-folder", "\n".join(l.split("│", 1)[1] for l in self.screen().splitlines() if "│" in l))
        self.settle()
        self.key("Enter")
        time.sleep(0.8)
        self.assertFalse(os.path.exists(self.out))

    def test_prompt_stays_in_sessions_mode_after_a_background_refresh(self):
        self.gh_repos_file("remote-only")
        self.seed_sessions()
        self.start(extra_env={"CLAUDE_HUB_E2E_SLEEP": "1"})
        self.ready()
        self.key("M-3")
        self.wait_for(lambda: "session>" in self.screen(), "sessions prompt", 8)
        lock = os.path.join(self.cache, "refresh.lock")
        self.wait_for(lambda: not os.path.exists(lock), "background refresh to finish", 10)
        time.sleep(1.5)                       # the watcher reloads and re-applies the prompt
        self.assertIn("session>", self.screen())
        self.assertNotIn("repo>", self.screen())

    def test_enter_on_a_background_session_attaches_it(self):
        self.open_sessions_view()
        self.type("Overnight")
        self.wait_for(lambda: "last activity" in self.screen() or "background session" in self.screen(), "preview", 8)
        self.settle()
        self.key("Enter")
        self.assertEqual(self.claude_call()["args"], "attach ab12cd34")

    def test_enter_on_a_past_session_resumes_it_in_its_directory(self):
        self.open_sessions_view()
        self.type("login")
        self.wait_for(lambda: "login is broken" in self.screen(), "past session preview shows the last prompt", 8)
        self.settle()
        self.key("Enter")
        call = self.claude_call()
        self.assertEqual(os.path.realpath(call["cwd"]), os.path.realpath(self.past_cwd))
        self.assertTrue(call["args"].endswith("--resume 22222222-bbbb"), call["args"])

    def test_ctrl_x_cleans_up_a_stale_entry_after_confirmation(self):
        self.open_sessions_view()
        self.type("Dead")
        self.wait_for(lambda: "stale: " in self.screen(), "stale preview", 8)
        self.settle()
        self.key("C-x")
        self.wait_for(lambda: "remove stale registry entry" in self.screen(), "confirmation prompt", 8)
        self.assertTrue(os.path.exists(self.stale_file), "must not delete before confirming")
        self.key("y", "Enter")
        self.wait_for(lambda: not os.path.exists(self.stale_file), "stale entry removed", 8)

    def test_plain_text_sessions_command(self):
        self.seed_sessions()
        env = dict(os.environ, HOME=self.home, CLAUDE_HUB_CACHE_DIR=self.cache,
                   CLAUDE_HUB_CONFIG=os.path.join(self.tmp, "config"))
        r = subprocess.run([sys.executable, HUB, "sessions"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Overnight build", r.stdout)
        self.assertIn("Fix the login bug", r.stdout)
        self.assertIn("sessions:", r.stdout)                 # the summary line
        self.assertIn("▶ working", r.stdout.splitlines()[-1])  # followed by the glyph key


    # --- badges and worktrees -----------------------------------------------
    def test_session_badge_and_worktree_grouping_in_the_project_list(self):
        alpha = os.path.join(self.root, "alpha")
        wt = os.path.join(self.root, "alpha-feature")
        git(["worktree", "add", "-q", "-b", "feature", wt], alpha)
        self.config_top("show_worktrees = true")
        cdir = os.path.join(self.home, ".claude", "sessions")
        os.makedirs(cdir)
        me = os.getpid()
        with open(f"/proc/{me}/stat") as f:
            start = f.read().rsplit(")", 1)[1].split()[19]
        for pid_off, cwd, name in ((0, alpha, "Fix alpha"), (0, self.home, "Home chat")):
            with open(os.path.join(cdir, f"{me}.{name[:3]}.json"), "w") as f:
                json.dump({"pid": me, "sessionId": f"sid-{name[:3]}-0000", "jobId": f"job{name[:3]}", "kind": "bg",
                           "status": "busy", "name": name, "cwd": cwd, "procStart": start,
                           "startedAt": 1_000, "updatedAt": 2_000}, f)
        self.start()
        self.ready()
        lines = self.screen().splitlines()
        rows = [l.split("│")[0] for l in lines]
        alpha_i = next(i for i, l in enumerate(rows) if l.lstrip(" ▌").startswith("⌂ alpha "))
        self.assertIn("⎇1", rows[alpha_i])
        self.assertIn("▶1", rows[alpha_i])
        self.assertTrue(rows[alpha_i + 1].lstrip(" ▌").startswith("↳ alpha-feature"), rows[alpha_i + 1])
        home = next(l for l in rows if "(home:" in l)
        self.assertIn("▶1", home)

    def test_worktree_row_launches_claude_in_the_worktree(self):
        alpha = os.path.join(self.root, "alpha")
        wt = os.path.join(self.root, "alpha-feature")
        git(["worktree", "add", "-q", "-b", "feature", wt], alpha)
        self.config_top("show_worktrees = true")
        self.start()
        self.ready()
        self.quiet()
        self.type("alpha-feature")
        self.wait_for(lambda: "1/5" in self.screen(), "list filtered to the worktree row")
        self.settle()
        self.key("Enter")
        self.assertEqual(os.path.realpath(self.claude_call()["cwd"]), os.path.realpath(wt))


    # --- review round ---------------------------------------------------------
    def test_header_leads_with_the_tab_bar_and_does_not_repeat_the_dashboard_stats(self):
        self.start()
        self.ready()
        self.wait_for(lambda: "dashboard" in self.screen(), "dashboard preview (home row is selected)")
        lines = self.screen().splitlines()
        header = [l.split("│")[0].rstrip() for l in lines[: self.prompt_row()]]
        self.assertTrue(header[0].lstrip().startswith("◂"), header)
        self.assertFalse(any("streak" in l for l in header), header)         # not duplicated in the left pane

    def test_ctrl_w_expands_and_collapses_worktrees(self):
        alpha = os.path.join(self.root, "alpha")
        git(["worktree", "add", "-q", "-b", "feature", os.path.join(self.root, "alpha-feature")], alpha)
        self.start()
        self.ready()
        self.quiet()
        self.assertNotIn("alpha-feature", self.screen().split("│")[0])
        self.assertIn("worktrees collapsed", self.screen())
        self.key("C-w")
        self.wait_for(lambda: "↳ alpha-feature" in self.screen() and "+T*" not in self.screen(), "worktree rows shown", 8)
        self.assertNotIn("worktrees collapsed", self.screen())
        self.settle()
        self.key("C-w")
        self.wait_for(lambda: "↳ alpha-feature" not in self.screen() and "+T*" not in self.screen(), "collapsed again", 8)

    def test_alt_h_shows_the_help_with_both_glyph_keys(self):
        self.start()
        self.ready()
        self.quiet()
        self.key("M-h")
        self.wait_for(lambda: "claude-hub keys" in self.screen(), "help in the preview", 8)
        screen = self.screen()
        for needle in ("continue last session", "◆ local + GitHub", "▶ working"):
            self.assertIn(needle, screen)

    def test_ages_resolve_inside_a_day(self):
        self.start()
        self.ready()
        rows = [l.split("│")[0] for l in self.screen().splitlines() if "alpha" in l.split("│")[0]]
        self.assertTrue(any("ago" in r or "just now" in r for r in rows), rows)   # e.g. "2h ago", not "today"

    # --- source tabs ---------------------------------------------------------
    def tab_is(self, name, extra=""):
        return lambda: f"[{name}" in self.screen() and "+T*" not in self.screen() and extra in self.screen()

    def test_ctrl_s_cycles_projects_other_sessions_and_wraps(self):
        self.gh_repos_file("remote-only")
        self.start()
        self.ready()
        self.quiet()
        self.assertIn("[Projects", self.screen())
        self.assertIn("alpha", self.list_rows())
        self.assertIn("remote-only", self.list_rows())             # local and GitHub share the one tab
        self.key("C-s")
        self.wait_for(self.tab_is("Other"), "Other tab", 8)
        self.assertNotIn("alpha", self.list_rows())
        self.settle()
        self.key("C-s")
        self.wait_for(lambda: "[Sessions" in self.screen() and "session>" in self.screen(), "Sessions tab", 8)
        self.settle()
        self.key("C-s")
        self.wait_for(lambda: "[Projects" in self.screen() and "repo>" in self.screen(), "wrapped to Projects", 8)

    def test_an_empty_tab_shows_a_placeholder_and_does_not_trap_input(self):
        self.start()                       # the sandbox has no folders or others' clones, so Other is empty
        self.ready()
        self.quiet()
        self.key("M-2")
        self.wait_for(lambda: "[Other" in self.screen() and "nothing in the Other tab" in self.screen(),
                      "placeholder in the empty Other tab", 8)
        self.assertNotIn("alpha", self.list_rows())     # the previous tab's rows must not linger
        self.settle()
        self.key("Enter")                               # Enter on the placeholder does nothing
        time.sleep(0.8)
        self.assertFalse(os.path.exists(self.out))
        self.key("M-1")                                 # and input still works: back to Projects
        self.wait_for(lambda: "[Projects" in self.screen() and "alpha" in self.screen(), "back to Projects", 8)

    def test_empty_sessions_tab_is_not_a_dead_end(self):
        self.start()                       # no .claude registry at all
        self.ready()
        self.quiet()
        self.key("M-3")
        self.wait_for(lambda: "[Sessions" in self.screen() and "nothing needs you" in self.screen(), "empty sessions", 8)
        self.settle()
        self.key("M-1")
        self.wait_for(lambda: "[Projects" in self.screen() and "alpha" in self.screen(), "keys still work", 8)

    def test_alt_s_goes_backwards_and_alt_number_jumps(self):
        self.start()
        self.ready()
        self.quiet()
        self.key("M-s")
        self.wait_for(lambda: "[Sessions" in self.screen() and "session>" in self.screen(), "previous from Projects wraps to Sessions", 8)
        self.settle()
        self.key("M-2")
        self.wait_for(self.tab_is("Other"), "alt-2 jumps to Other", 8)

    def test_start_tab_comes_from_config(self):
        self.gh_repos_file("remote-only")
        cfg_path = os.path.join(self.tmp, "config")
        with open(cfg_path) as f:
            body = f.read()
        with open(cfg_path, "w") as f:
            f.write('start_tab = "other"\n' + body)      # top-level keys must precede the [tags] table
        self.start()
        self.wait_for(lambda: "repo>" in self.screen() and "[Other" in self.screen(), "picker on the Other tab", 10)
        self.assertNotIn("alpha", self.list_rows())

    def test_rows_show_a_source_glyph_and_an_honest_origin(self):
        self.gh_repos_file("remote-only")
        self.start()
        self.ready()
        self.quiet()
        rows = [l.split("│")[0].lstrip(" ▌") for l in self.screen().splitlines()]
        alpha = next(r for r in rows if r.startswith("⌂ alpha"))
        remote = next(r for r in rows if r.startswith("◌ remote-only"))
        self.assertIn("dir:root", alpha)              # a scan root, named as a directory, never as "github"
        self.assertIn("gh:o", remote)
        self.assertNotRegex(alpha, r"\bgithub\b")

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
