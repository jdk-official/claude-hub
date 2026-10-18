"""Tests for bin/claude-hub. Run: python3 -m unittest discover -s tests -v"""
import glob
import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = os.path.join(ROOT, "bin", "claude-hub")


os.environ.setdefault("CLAUDE_HUB_NO_AGENTS", "1")   # never ask a real or fake claude to list sessions


def load_hub():
    loader = importlib.machinery.SourceFileLoader("hub_mod", HUB)
    spec = importlib.util.spec_from_loader("hub_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


hub = load_hub()


def sh(args, cwd, env=None):
    e = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    e.update(env or {})
    subprocess.run(args, cwd=cwd, env=e, check=True, capture_output=True)


def make_repo(path, remote=None, commits=1, dirty=False, date="2026-10-01T12:00:00"):
    os.makedirs(path)
    sh(["git", "init", "-q", "-b", "main"], path)
    for i in range(commits):
        with open(os.path.join(path, f"f{i}.txt"), "w") as f:
            f.write(str(i))
        sh(["git", "add", "-A"], path)
        sh(["git", "-c", "user.name=T", "-c", "user.email=jonathan@kyte.me.uk",
            "commit", "-q", "-m", f"c{i}"], path,
           env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
    if remote:
        sh(["git", "remote", "add", "origin", remote], path)
    if dirty:
        with open(os.path.join(path, "dirty.txt"), "w") as f:
            f.write("x")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hubtest-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = os.path.join(self.tmp, "cache")
        p = mock.patch.object(hub, "CACHE_DIR", self.cache)
        p.start()
        self.addCleanup(p.stop)


class RemoteSlug(unittest.TestCase):
    def test_forms(self):
        f = hub.slug_from_remote
        self.assertEqual(f("git@github.com:jdk-official/hub.git"), "jdk-official/hub")
        self.assertEqual(f("https://github.com/jdk-official/hub"), "jdk-official/hub")
        self.assertEqual(f("https://user@github.com/o/n.git/"), "o/n")
        self.assertEqual(f("ssh://git@github.com/o/n.git"), "o/n")
        self.assertEqual(f("git@gitlab.com:o/n.git"), "")
        self.assertEqual(f(""), "")


class Config(Tmp):
    def write(self, text):
        p = os.path.join(self.tmp, "config")
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_missing_file_gives_defaults(self):
        cfg, warn = hub.load_config(os.path.join(self.tmp, "nope"))
        self.assertIsNone(warn)
        self.assertEqual(cfg["owners"], ["jdk-official"])
        self.assertEqual(cfg["count"], 10)

    def test_valid_values(self):
        p = self.write('owners=["a"]\npinned=["x"]\nhidden=["y"]\ncount=5\n'
                       'scan_roots=["~/code"]\n[tags]\nx=["tools"]\n')
        cfg, warn = hub.load_config(p)
        self.assertIsNone(warn)
        self.assertEqual(cfg["owners"], ["a"])
        self.assertEqual(cfg["pinned"], ["x"])
        self.assertEqual(cfg["count"], 5)
        self.assertEqual(cfg["tags"], {"x": ["tools"]})
        self.assertTrue(cfg["scan_roots"][0].endswith("/code"))
        self.assertFalse(cfg["scan_roots"][0].startswith("~"))

    def test_bad_toml_falls_back(self):
        cfg, warn = hub.load_config(self.write("owners = [unclosed"))
        self.assertIn("ignored", warn)
        self.assertEqual(cfg["owners"], ["jdk-official"])

    def test_bad_types_ignored_individually(self):
        cfg, warn = hub.load_config(self.write('count = "ten"\npinned = ["ok"]\n'))
        self.assertEqual(cfg["count"], 10)
        self.assertEqual(cfg["pinned"], ["ok"])
        self.assertIn("count", warn)


class Cache(Tmp):
    def test_missing_is_empty(self):
        self.assertEqual(hub.load_cache(), {})

    def test_corrupt_is_ignored_and_rebuilt(self):
        os.makedirs(self.cache)
        with open(hub.cache_file(), "w") as f:
            f.write("{not json")
        self.assertEqual(hub.load_cache(), {})
        hub.save_cache_section(gh={"ok": True, "repos": []})
        self.assertEqual(hub.load_cache()["gh"]["ok"], True)

    def test_sections_merge(self):
        hub.save_cache_section(gh={"ok": True, "repos": []})
        hub.save_cache_section(prs={"a/b": {"pr_count": 2}})
        c = hub.load_cache()
        self.assertIn("gh", c)
        self.assertEqual(c["prs"]["a/b"]["pr_count"], 2)

    def test_status_lines(self):
        now = 1_000_000.0
        f = hub.gh_status_line
        self.assertIn("not installed", f({}, False, now))
        self.assertIn("loading", f({}, True, now))
        self.assertIn("unavailable, local only", f({"gh": {"ok": False, "fetched_at": now}}, True, now))
        self.assertIn("unavailable (cached 2h ago)",
                      f({"gh": {"ok": False, "fetched_at": now - 7200, "repos": [{}]}}, True, now))
        self.assertEqual(f({"gh": {"ok": True, "fetched_at": now - 300, "repos": [{}]}}, True, now), "")   # healthy: silent
        self.assertEqual(f({"gh": {"ok": True, "fetched_at": now - 20 * 3600, "repos": [{}]}}, True, now), "")
        self.assertIn("STALE", f({"gh": {"ok": True, "fetched_at": now - 90000, "repos": []}}, True, now))

    def test_header_shows_the_github_line_only_when_something_is_wrong(self):
        cfg = dict(hub.DEFAULT_CONFIG)
        now = time.time()
        os.environ.pop("CLAUDE_HUB_MODE_STATE", None)
        healthy = {"gh": {"ok": True, "fetched_at": now - 60, "repos": [{"name": "a", "owner": "o"}]}}
        self.assertFalse(any(l.startswith("GitHub") for l in hub.header_lines(healthy, cfg, None, True, [])))
        for bad, word in (({}, "loading"), ({"gh": {"ok": False, "fetched_at": now, "repos": []}}, "unavailable"),
                          ({"gh": {"ok": True, "fetched_at": now - 90000, "repos": []}}, "STALE")):
            self.assertTrue(any(l.startswith("GitHub") and word in l for l in hub.header_lines(bad, cfg, None, True, [])), word)
        self.assertTrue(any("not installed" in l for l in hub.header_lines({}, cfg, None, False, [])))


def entry(name, slug="", ts=0, dirty=0, ahead=0, gh=None, local=True, origin="x"):
    l = {"name": name, "path": "/p/" + name, "root": "/p", "is_git": True, "ts": ts, "branch": "main",
         "dirty": dirty, "ahead": ahead, "behind": 0, "has_upstream": True, "remote": "", "slug": slug}
    return {"name": name, "slug": slug, "path": l["path"] if local else "", "local": l if local else None,
            "gh": gh, "ts": ts, "origin": origin}


class Ordering(unittest.TestCase):
    cfg = {"pinned": [], "hidden": [], "owners": [], "scan_roots": [], "tags": {}, "count": 10}

    def test_recency(self):
        es = [entry("old", ts=1), entry("new", ts=9)]
        self.assertEqual([e["name"] for e in hub.order_entries(es, self.cfg)], ["new", "old"])

    def test_dirty_does_not_outrank_newer_clean(self):
        es = [entry("dirty-old", ts=1, dirty=2), entry("clean-new", ts=100)]
        self.assertEqual(hub.order_entries(es, self.cfg)[0]["name"], "clean-new")

    def test_ahead_and_pr_count_do_not_reorder(self):
        es = [entry("b", ts=1, ahead=1), entry("a", ts=9),
              entry("c", slug="o/c", ts=2, gh={"name": "c", "owner": "o", "pr_count": 1})]
        order = hub.order_entries(es, self.cfg)
        self.assertEqual([e["name"] for e in order], ["a", "c", "b"])

    def test_claude_session_counts_as_use(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        proj = os.path.join(d, "projects", "-work-used")
        os.makedirs(proj)
        open(os.path.join(proj, "s.jsonl"), "w").close()
        os.utime(os.path.join(proj, "s.jsonl"), (500, 500))
        with mock.patch.dict(os.environ, {"CLAUDE_HUB_CLAUDE_DIR": d}):
            self.assertEqual(hub.last_claude_use("/work/used"), 500)
            self.assertEqual(hub.last_claude_use("/work/never"), 0)

    def test_pinned_first_in_config_order(self):  # AC-18
        cfg = dict(self.cfg, pinned=["b", "a"])
        es = [entry("a", ts=5), entry("x", ts=99, dirty=3), entry("b", ts=1)]
        self.assertEqual([e["name"] for e in hub.order_entries(es, cfg)], ["b", "a", "x"])

    def test_markers(self):
        cfg = dict(self.cfg, pinned=["a"])
        m = hub.markers(entry("a", dirty=3, ahead=2, slug="o/a", gh={"pr_count": 1}), cfg)
        self.assertEqual(m, "★ ●3 ↑2 PR1")
        self.assertEqual(hub.markers(entry("g", local=False), self.cfg), "")   # the source glyph says GitHub-only


class Merge(unittest.TestCase):
    cfg = {"pinned": [], "hidden": [], "owners": [], "scan_roots": [], "tags": {}, "count": 10}

    def local(self, name, slug="", ts=1, root="/mnt/data/github"):
        return {"name": name, "path": f"{root}/{name}", "root": root, "is_git": True, "ts": ts,
                "branch": "main", "dirty": 0, "ahead": 0, "behind": 0, "has_upstream": False,
                "remote": "", "slug": slug}

    def gh(self, name, owner="jdk-official", archived=False):
        return {"name": name, "owner": owner, "pushedAt": "2026-10-01T00:00:00Z",
                "isArchived": archived, "visibility": "PRIVATE", "description": "d"}

    def test_local_and_gh_merge_by_slug(self):
        es = hub.build_entries([self.local("hub", "jdk-official/hub")], [self.gh("hub")], self.cfg)
        self.assertEqual(len(es), 1)
        self.assertIsNotNone(es[0]["gh"])
        self.assertIsNotNone(es[0]["local"])

    def test_same_name_different_owner_both_listed(self):  # S7
        es = hub.build_entries([self.local("x", "other/x")], [self.gh("x")], self.cfg)
        self.assertEqual(len(es), 2)
        self.assertEqual({e["origin"] for e in es}, {"gh:other", "gh:jdk-official"})

    def test_two_clones_of_one_remote_dedup(self):
        es = hub.build_entries(
            [self.local("hub", "o/hub", ts=5), self.local("hub-copy", "o/hub", ts=9, root="/mnt/data/scratch")],
            [], self.cfg)
        self.assertEqual([e["name"] for e in es], ["hub-copy"])

    def test_hidden_and_archived_omitted(self):  # AC-17
        cfg = dict(self.cfg, hidden=["secret"])
        es = hub.build_entries([self.local("secret")], [self.gh("old", archived=True), self.gh("ok")], cfg)
        self.assertEqual([e["name"] for e in es], ["ok"])

    def test_origin_label_for_non_remote_dirs(self):
        es = hub.build_entries([self.local("notes", root="/mnt/data/files")], [], self.cfg)
        self.assertEqual(es[0]["origin"], "dir:files")


class Excerpt(Tmp):
    def test_handover_root_beats_docs_and_readme(self):
        d = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(d, "docs"))
        for rel, text in (("HANDOVER.md", "root handover"), ("docs/HANDOVER.md", "docs handover"),
                          ("README.md", "readme")):
            with open(os.path.join(d, rel), "w") as f:
                f.write(text)
        self.assertEqual(hub.excerpt(d), ("HANDOVER.md", ["root handover"]))

    def test_docs_handover_then_readme(self):  # AC-24
        d = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(d, "docs"))
        with open(os.path.join(d, "README.md"), "w") as f:
            f.write("# T\n\nline\n")
        self.assertEqual(hub.excerpt(d)[0], "README.md")
        with open(os.path.join(d, "docs", "HANDOVER.md"), "w") as f:
            f.write("---\nupdated: x\n---\n\n# H\nbody\n")
        name, lines = hub.excerpt(d)
        self.assertEqual(name, "HANDOVER.md")
        self.assertEqual(lines, ["# H", "body"])

    def test_limited_to_ten_lines(self):
        d = os.path.join(self.tmp, "r")
        os.makedirs(d)
        with open(os.path.join(d, "README.md"), "w") as f:
            f.write("\n".join(f"l{i}" for i in range(40)))
        self.assertEqual(len(hub.excerpt(d)[1]), 10)

    def test_none(self):
        d = os.path.join(self.tmp, "empty")
        os.makedirs(d)
        self.assertEqual(hub.excerpt(d), ("", []))


class Scan(Tmp):
    def test_git_and_plain_dirs(self):
        root = os.path.join(self.tmp, "root")
        os.makedirs(root)
        make_repo(os.path.join(root, "r1"), remote="git@github.com:o/r1.git", dirty=True)
        os.makedirs(os.path.join(root, "plain"))
        os.makedirs(os.path.join(root, ".hidden"))
        found = {l["name"]: l for l in hub.scan_local([root, os.path.join(self.tmp, "missing")])}
        self.assertEqual(set(found), {"r1", "plain"})
        self.assertTrue(found["r1"]["is_git"])
        self.assertEqual(found["r1"]["dirty"], 1)
        self.assertEqual(found["r1"]["slug"], "o/r1")
        self.assertEqual(found["r1"]["branch"], "main")
        self.assertFalse(found["plain"]["is_git"])
        self.assertGreater(found["plain"]["ts"], 0)


class CloneAbort(Tmp):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "clones")
        os.makedirs(self.root)
        p = mock.patch.object(hub, "CLONE_ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)

    def test_answer_n_leaves_nothing(self):  # AC-4
        with mock.patch("builtins.input", return_value="n"), \
                mock.patch.object(hub.shutil, "which", return_value="/usr/bin/gh"):
            with self.assertRaises(SystemExit):
                hub.clone_repo("o/x", "x")
        self.assertEqual(os.listdir(self.root), [])

    def test_failed_clone_removes_partial_dir(self):  # AC-5
        def fake_run(args, **kw):
            os.makedirs(args[-1])  # gh leaves a partial directory behind
            return subprocess.CompletedProcess(args, 1)
        with mock.patch("builtins.input", return_value="y"), \
                mock.patch.object(hub.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(hub.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as cm:
                hub.clone_repo("o/x", "x")
        self.assertIn("nothing was left", str(cm.exception))
        self.assertEqual(os.listdir(self.root), [])

    def test_success_returns_target(self):
        def fake_run(args, **kw):
            os.makedirs(args[-1])
            return subprocess.CompletedProcess(args, 0)
        with mock.patch("builtins.input", return_value="y"), \
                mock.patch.object(hub.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(hub.subprocess, "run", side_effect=fake_run):
            self.assertEqual(hub.clone_repo("o/x", "x"), os.path.join(self.root, "x"))


class Cli(Tmp):
    """Run bin/claude-hub as a subprocess with a sandboxed HOME, config and PATH."""

    def env(self, path=None):
        e = dict(os.environ)
        e.update(HOME=self.tmp, CLAUDE_HUB_CACHE_DIR=self.cache,
                 CLAUDE_HUB_CONFIG=os.path.join(self.tmp, "config"),
                 PATH=path if path is not None else os.environ["PATH"])
        return e

    def test_missing_fzf_is_one_line_no_traceback(self):  # AC-8
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        for tool in ("git", "claude"):
            os.symlink(shutil.which("git") or "/usr/bin/git", os.path.join(bindir, tool))
        r = subprocess.run([sys.executable, HUB], env=self.env(bindir), capture_output=True, text=True)
        self.assertEqual(r.returncode, 127)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertIn("fzf", r.stderr)

    def test_list_without_gh_shows_local(self):  # AC-7
        root = os.path.join(self.tmp, "root")
        make_repo(os.path.join(root, "alpha"))
        with open(os.path.join(self.tmp, "config"), "w") as f:
            f.write(f'scan_roots=["{root}"]\n')
        gitdir = os.path.dirname(shutil.which("git"))
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        os.symlink(shutil.which("git"), os.path.join(bindir, "git"))
        r = subprocess.run([sys.executable, HUB, "--list"], env=self.env(bindir),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alpha", r.stdout)
        self.assertIn("home", r.stdout)
        self.assertNotEqual(gitdir, "")

    def test_gather_never_waits_on_gh(self):  # AC-1
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        slow = os.path.join(bindir, "gh")
        with open(slow, "w") as f:
            f.write("#!/bin/sh\nsleep 30\n")
        os.chmod(slow, os.stat(slow).st_mode | stat.S_IXUSR)
        cfg = dict(hub.DEFAULT_CONFIG, scan_roots=[])
        with mock.patch.dict(os.environ, {"PATH": bindir + os.pathsep + os.environ["PATH"]}):
            t = time.time()
            hub.gather(cfg)
            hub.gh_status_line({}, True)
        self.assertLess(time.time() - t, 2)


class ClaudeArgs(Tmp):
    def test_plain_start_and_continue(self):
        self.assertEqual(hub.claude_argv(False), ["claude"])
        self.assertEqual(hub.claude_argv(True), ["claude", "--continue"])

    def test_no_plugin_dir_is_added_any_more(self):
        mod = os.path.join(self.tmp, ".claude", "mods", "project-dashboard")
        os.makedirs(mod)      # even if an old mod directory exists: the feature is an enabled plugin now
        self.assertNotIn("--plugin-dir", hub.claude_argv(False, home=self.tmp))


class PreviewLayout(unittest.TestCase):
    def test_threshold_is_in_preview_columns_not_terminal_columns(self):
        # 45% of a 100-column terminal is 45, so the alternative layout kicks in below 100 columns
        # list priority: 38% preview; stacked below until the terminal is ~121 columns (38% of 121 = 46)
        self.assertIn("right,38%", hub.PREVIEW_WINDOW)
        self.assertIn("<46(down", hub.PREVIEW_WINDOW)


class Dashboard(Tmp):
    def test_home_preview_shows_heatmap_and_streak(self):
        from datetime import date
        today = date.today().isoformat()
        hub.save_cache_section(stats={"computed_at": 1, "days": {today: {"c": 3, "ins": 5, "del": 1, "repos": ["a"]}},
                                      "repo_weeks": {}, "partial": 0})
        text = hub.preview_text(os.path.expanduser("~"), "", "~", 60)
        self.assertIn("Mon", text)
        self.assertIn("streak 1d", text)
        self.assertIn("Markers:", text)
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", text)   # width is what the user sees, not escape bytes
        self.assertLessEqual(max(len(l) for l in plain.splitlines()), 80)

    def test_home_preview_without_stats(self):
        self.assertIn("computing", hub.preview_text("/home/x", "", "~", 60))


class Preview(Tmp):
    def test_preview_wraps_and_has_commits_and_excerpt(self):  # FR-17/18/20
        d = os.path.join(self.tmp, "proj")
        make_repo(d, commits=2)
        with open(os.path.join(d, "README.md"), "w") as f:
            f.write("# Proj\n" + "word " * 60 + "\n")
        text = hub.preview_text(d, "", "proj", width=40)
        self.assertIn("c1", text)
        self.assertIn("README.md:", text)
        self.assertLessEqual(max(len(l) for l in text.splitlines()), 40 + 2)

    def test_gh_only_preview_says_not_cloned(self):
        text = hub.preview_text("", "o/x", "x", width=50)
        self.assertIn("not cloned", text)


class Stats(Tmp):
    from datetime import date as _d
    D = staticmethod(lambda s: __import__("datetime").date.fromisoformat(s))

    def days(self, spec):
        return {k: {"c": c, "ins": i, "del": d, "repos": r} for k, (c, i, d, r) in spec.items()}

    def test_qualifies(self):
        q = hub.qualifies
        self.assertTrue(q("J", "jonathan@kyte.me.uk", ""))
        self.assertTrue(q("J", "1234+jdk-official@users.noreply.github.com", ""))
        self.assertFalse(q("Other", "other@example.com", ""))
        self.assertFalse(q("dependabot[bot]", "jonathan@kyte.me.uk", ""))
        self.assertTrue(q("Bot", "x@example.com", "Claude Sonnet 5.5 <noreply@anthropic.com>"))

    def test_parse_log_shortstat(self):
        text = ("@@h1\x1fa@b\x1fN\x1f2026-10-01\x1f\n\n 2 files changed, 10 insertions(+), 3 deletions(-)\n"
                "@@h2\x1fa@b\x1fN\x1f2026-10-02\x1f\n\n 1 file changed, 1 deletion(-)\n")
        c = hub.parse_log(text)
        self.assertEqual([(x["ins"], x["del"]) for x in c], [(10, 3), (0, 1)])

    def test_streak_today_active(self):
        D = self.D
        act = {D("2026-10-11"), D("2026-10-12"), D("2026-10-13")}
        self.assertEqual(hub.streaks(act, D("2026-10-13")), (3, 3))

    def test_streak_survives_empty_today(self):  # AC-10 / D-7
        D = self.D
        act = {D("2026-10-11"), D("2026-10-12")}
        self.assertEqual(hub.streaks(act, D("2026-10-13"))[0], 2)

    def test_streak_resets_after_full_empty_day(self):  # AC-11
        D = self.D
        self.assertEqual(hub.streaks({D("2026-10-10")}, D("2026-10-13"))[0], 0)

    def test_best_streak(self):
        D = self.D
        act = {D("2026-09-01"), D("2026-09-02"), D("2026-09-03"), D("2026-10-12")}
        self.assertEqual(hub.streaks(act, D("2026-10-13")), (1, 3))

    def test_period_totals_and_week_boundary(self):  # Monday-based weeks
        D = self.D
        days = self.days({"2026-10-12": (2, 10, 1, ["a"]), "2026-10-13": (1, 5, 0, ["a", "b"]),
                          "2026-10-11": (9, 99, 99, ["z"])})
        today = D("2026-10-13")  # a Tuesday
        self.assertEqual(hub.monday(today), D("2026-10-12"))
        self.assertEqual(hub.period_totals(days, hub.monday(today), today), (3, 2, 15, 1))
        self.assertEqual(hub.period_totals(days, today, today), (1, 2, 5, 0))

    def test_avg_uses_four_complete_prior_weeks(self):
        D = self.D
        days = self.days({"2026-10-05": (8, 0, 0, []), "2026-09-28": (4, 0, 0, []),
                          "2026-09-21": (0, 0, 0, []), "2026-09-14": (4, 0, 0, []),
                          "2026-10-13": (50, 0, 0, [])})
        self.assertEqual(hub.avg_weekly_commits(days, D("2026-10-13")), 4.0)

    def test_sparkline_flat_and_single_bar(self):  # AC-13, AC-14
        D = self.D
        today = D("2026-10-13")
        self.assertEqual(hub.sparkline({}, today), "▁" * 8)
        one = hub.sparkline({"2026-09-28": 3}, today)
        self.assertEqual(sorted(set(one)), ["▁", "█"])
        self.assertEqual(one.count("█"), 1)
        self.assertEqual(len(one), 8)

    def test_heatmap_shape_and_width(self):  # AC-16
        D = self.D
        today = D("2026-10-13")
        days = self.days({"2026-10-12": (3, 0, 0, []), "2026-10-13": (1, 0, 0, [])})
        lines = hub.heatmap(days, today)
        self.assertEqual(len(lines), 8)
        self.assertLessEqual(max(len(l) for l in lines), 80)
        self.assertTrue(lines[0].startswith("Mon"))
        self.assertIn("█", lines[0])   # Monday 2026-10-12 holds the max
        self.assertIn("▒", lines[1])   # Tuesday today: 1 of max 3
        self.assertNotIn("\x1b", "".join(lines))  # plain by default

    def test_heatmap_color_mode(self):
        D = self.D
        days = self.days({"2026-10-12": (3, 0, 0, []), "2026-10-13": (1, 0, 0, [])})
        lines = hub.heatmap(days, D("2026-10-13"), color=True)
        self.assertIn("\x1b[38;5;40m■", lines[0])   # busiest day uses the top green
        self.assertIn("\x1b[38;5;238m■", lines[0])  # empty days use the dim grey

    def test_repo_commits_end_to_end(self):
        r = os.path.join(self.tmp, "repo")
        os.makedirs(r)
        sh(["git", "init", "-q", "-b", "main"], r)
        today = time.strftime("%Y-%m-%dT12:00:00")

        def commit(name, email, msg, fname):
            with open(os.path.join(r, fname), "w") as f:
                f.write("a\nb\n")
            sh(["git", "add", "-A"], r)
            sh(["git", "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-q", "-m", msg],
               r, env={"GIT_AUTHOR_DATE": today, "GIT_COMMITTER_DATE": today})
        commit("Me", "jonathan@kyte.me.uk", "mine", "a")
        commit("Stranger", "s@example.com", "theirs", "b")
        commit("dependabot[bot]", "bot@example.com", "bump", "c")
        commit("Helper", "h@example.com",
               "paired\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>", "d")
        commits = hub.repo_commits(r)
        self.assertEqual(len(commits), 2)  # mine + the Claude co-authored one
        self.assertTrue(all(c["ins"] == 2 for c in commits))
        st = hub.aggregate({r: ("repo", commits)})
        day = time.strftime("%Y-%m-%d")
        self.assertEqual(st["days"][day]["c"], 2)
        self.assertEqual(st["days"][day]["ins"], 4)
        self.assertEqual(sum(st["repo_weeks"][r].values()), 2)

    def test_compute_stats_dedups_same_remote(self):
        a, b = os.path.join(self.tmp, "a"), os.path.join(self.tmp, "b")
        for r in (a, b):
            make_repo(r, remote="git@github.com:o/same.git", date=time.strftime("%Y-%m-%dT12:00:00"))
        st = hub.compute_stats(hub.scan_local([self.tmp]))
        self.assertEqual(sum(v["c"] for v in st["days"].values()), 1)

    def test_header_when_no_stats(self):
        self.assertIn("computing", hub.stats_header({})[0])

    def test_header_with_stats(self):
        D = self.D
        days = self.days({"2026-10-13": (2, 1500, 20, ["a"]), "2026-10-12": (1, 1, 1, ["b"])})
        lines = hub.stats_header({"stats": {"days": days}}, today=D("2026-10-13"))
        self.assertIn("streak 2d", lines[0])
        self.assertIn("today 2c 1r +1.5k/-20", lines[0])
        self.assertIn("week 3c 2r", lines[1])


class ReviewRegressions(Tmp):
    """One test per finding from the independent review of iteration 1."""

    def fake_run(self, table):
        def run(args, cwd=None, timeout=3):
            for key, val in table.items():
                if key in " ".join(args):
                    return val
            return (1, "", "boom")
        return run

    def test_h1_failed_refresh_keeps_cached_repos(self):
        prev = {"fetched_at": 111.0, "ok": True,
                "repos": [{"name": "a", "owner": "o"}, {"name": "b", "owner": "p"}]}
        with mock.patch.object(hub, "run", self.fake_run({"repo list o": (1, "", "no network"),
                                                         "repo list p": (0, json.dumps([{"name": "b2"}]), "")})):
            out = hub.fetch_github(["o", "p"], prev)
        names = sorted(r["name"] for r in out["repos"])
        self.assertEqual(names, ["a", "b2"])          # o kept from cache, p refreshed
        self.assertFalse(out["ok"])
        self.assertEqual(out["fetched_at"], 111.0)     # stale marker not reset by a failure

    def test_h1_all_ok_updates_fetched_at(self):
        with mock.patch.object(hub, "run", self.fake_run({"repo list": (0, "[]", "")})):
            out = hub.fetch_github(["o"], {"fetched_at": 1.0, "repos": []})
        self.assertTrue(out["ok"])
        self.assertGreater(out["fetched_at"], 1.0)

    def test_m2_target_appearing_after_prompt_is_never_deleted(self):
        root = os.path.join(self.tmp, "clones")
        os.makedirs(root)
        mine = os.path.join(root, "x")

        def answer(_):
            os.makedirs(mine)               # another session cloned it while we were prompting
            with open(os.path.join(mine, "work.txt"), "w") as f:
                f.write("keep")
            return "y"
        with mock.patch.object(hub, "CLONE_ROOT", root), mock.patch("builtins.input", side_effect=answer), \
                mock.patch.object(hub.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(hub.subprocess, "run") as r:
            self.assertEqual(hub.clone_repo("o/x", "x"), mine)
        r.assert_not_called()
        self.assertTrue(os.path.exists(os.path.join(mine, "work.txt")))

    def test_m2_unsafe_names_refused(self):
        for bad in ("..", "a/b", "x\ny", ""):
            with self.assertRaises(SystemExit):
                hub.clone_repo("o/x", bad)

    def test_fr27_unreachable_github_refuses_before_prompting(self):
        root = os.path.join(self.tmp, "clones")
        os.makedirs(root)
        hub.save_cache_section(gh={"ok": False, "repos": [], "fetched_at": 1, "last_attempt": 2})
        with mock.patch.object(hub, "CLONE_ROOT", root), mock.patch.object(hub.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(hub, "github_reachable", return_value=False), \
                mock.patch("builtins.input", side_effect=AssertionError("must not prompt")):
            with self.assertRaises(SystemExit) as cm:
                hub.clone_repo("o/x", "x")
        self.assertIn("unreachable", str(cm.exception))

    def test_m3_concurrent_cache_updates_do_not_lose_entries(self):
        import threading
        errs = []

        def w(i):
            try:
                hub.update_cache(lambda c: c.setdefault("prs", {}).__setitem__(f"o/r{i}", {"pr_count": i, "fetched_at": 1}))
            except Exception as e:   # pragma: no cover
                errs.append(e)
        th = [threading.Thread(target=w, args=(i,)) for i in range(12)]
        [t.start() for t in th]
        [t.join() for t in th]
        self.assertEqual(errs, [])
        self.assertEqual(len(hub.load_cache()["prs"]), 12)
        self.assertEqual([f for f in os.listdir(self.cache) if f.endswith(".tmp")], [])

    def test_m4_issues_disabled_still_counts_prs_and_caches(self):
        hub.save_cache_section(gh={"ok": True, "repos": [], "fetched_at": 1, "last_attempt": 1})
        calls = []

        def run(args, cwd=None, timeout=3):
            calls.append(args[1])
            if args[1] == "pr":
                return 0, json.dumps([{"title": "p1"}, {"title": "p2"}]), ""
            return 1, "", "issues disabled"
        with mock.patch.object(hub, "run", run), mock.patch.object(hub.shutil, "which", return_value="/x/gh"):
            out = hub.fetch_prs("o/r")
            self.assertEqual(out["pr_count"], 2)
            self.assertTrue(out["issue_error"])
            n = len(calls)
            hub.fetch_prs("o/r")                  # served from cache within the TTL
        self.assertEqual(len(calls), n)

    def test_m5_stats_union_clones_and_key_on_picked_path(self):
        a, b = os.path.join(self.tmp, "old"), os.path.join(self.tmp, "new")
        today = time.strftime("%Y-%m-%dT12:00:00")
        make_repo(a, remote="git@github.com:o/same.git", date=today)
        make_repo(b, remote="git@github.com:o/same.git", commits=2, date=today)
        local = hub.scan_local([self.tmp])
        for l in local:                            # make "new" the most recent clone
            l["ts"] = 200 if l["name"] == "new" else 100
        st = hub.compute_stats(local)
        self.assertEqual(list(st["repo_weeks"]), [b])
        self.assertEqual(sum(v["c"] for v in st["days"].values()), 2)

    def test_m6_git_runs_with_config_code_execution_disabled(self):
        seen = []
        with mock.patch.object(hub, "run", lambda args, cwd=None, timeout=3: (seen.append(args), (0, "", ""))[1]):
            hub.git(["status"], "/tmp")
        joined = " ".join(seen[0])
        self.assertIn("core.fsmonitor=false", joined)
        self.assertIn("core.hooksPath=/dev/null", joined)

    def test_m6_fsmonitor_in_repo_config_does_not_execute(self):
        r = os.path.join(self.tmp, "evil")
        make_repo(r)
        marker = os.path.join(self.tmp, "pwned")
        sh(["git", "config", "core.fsmonitor", f"touch {marker}; true"], r)
        hub.inspect_dir(self.tmp, r)
        hub.repo_commits(r)
        self.assertFalse(os.path.exists(marker))

    def test_l1_status_timeout_is_unknown_not_clean(self):
        d = os.path.join(self.tmp, "r")
        make_repo(d)
        real = hub.run

        def run(args, cwd=None, timeout=3):
            if "status" in args:
                return 1, "", "timed out"
            return real(args, cwd=cwd, timeout=timeout)
        with mock.patch.object(hub, "run", run):
            l = hub.inspect_dir(self.tmp, d)
        self.assertEqual(l["dirty"], -1)
        e = {"name": "r", "slug": "", "path": d, "local": l, "gh": None, "ts": 0, "origin": ""}
        self.assertIn("?", hub.state_text(e))
        self.assertNotIn("clean", hub.state_text(e))

    def test_l1_commit_timeout_marks_stats_partial(self):
        d = os.path.join(self.tmp, "r")
        make_repo(d)
        with mock.patch.object(hub, "repo_commits", return_value=None):
            st = hub.compute_stats(hub.scan_local([self.tmp]))
        self.assertEqual(st["partial"], 1)
        self.assertIn("partial", hub.stats_header({"stats": st})[1])

    def test_l2_no_double_ago(self):
        line = hub.gh_status_line({"gh": {"ok": False, "fetched_at": 100.0, "repos": [{}]}}, True, now=110.0)
        self.assertNotIn("ago ago", line)
        self.assertIn("just now", line)

    def test_l3_schema_corrupt_cache_does_not_crash(self):
        os.makedirs(self.cache)
        bad = {"version": 1, "gh": "x", "prs": [], "stats": {"days": {"not-a-date": {"c": 1}, "2026-10-01": 5}}}
        with open(hub.cache_file(), "w") as f:
            json.dump(bad, f)
        c = hub.load_cache()
        self.assertNotIn("gh", c)
        self.assertEqual(c["stats"]["days"], {})
        self.assertTrue(hub.gh_status_line(c, True))
        self.assertTrue(hub.stats_header(c))

    def test_l4_control_characters_do_not_break_fields(self):
        cfg = hub.load_config(os.path.join(self.tmp, "none"))[0]
        e = {"name": "r", "slug": "o/r", "path": "/p/r", "local": None, "origin": "o", "ts": 1,
             "gh": {"description": "tab\there\nnewline", "visibility": "PUBLIC", "name": "r", "owner": "o"}}
        line = hub.fzf_lines([e], cfg, {})[1]
        self.assertEqual(len(line.split("\t")), 7)

    def test_l5_git_file_counts_as_repo(self):
        wt = os.path.join(self.tmp, "wt")
        os.makedirs(wt)
        with open(os.path.join(wt, ".git"), "w") as f:
            f.write("gitdir: /nowhere\n")
        self.assertTrue(hub.inspect_dir(self.tmp, wt)["is_git"])

    def test_l6_identity_is_strict(self):
        q = hub.qualifies
        self.assertTrue(q("x", "42+jdk-official@users.noreply.github.com", ""))
        self.assertFalse(q("x", "notjdk-official@users.noreply.github.com", ""))
        self.assertFalse(q("x", "jdk-official-evil@users.noreply.github.com", ""))
        self.assertFalse(q("x", "x@example.com", "Claudia Smith <claudia@example.com>"))
        self.assertTrue(q("x", "x@example.com", "Claude <noreply@anthropic.com>"))


class Iteration2Units(Tmp):
    """Unit coverage for the iteration-2 plumbing the review found untested."""

    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.tmp, "tag.state")
        p = mock.patch.dict(os.environ, {"CLAUDE_HUB_TAG_STATE": self.state})
        p.start()
        self.addCleanup(p.stop)
        self.cfg = dict(hub.DEFAULT_CONFIG, tags={"a": ["x"], "b": ["y", "x"]})

    def test_cycle_tag_wraps_through_all_tags_and_none(self):
        self.assertEqual(hub.all_tags(self.cfg), ["x", "y"])
        self.assertEqual(hub.current_tag(), "")
        seq = [hub.cycle_tag(self.cfg) for _ in range(4)]
        self.assertEqual(seq, ["x", "y", "", "x"])
        self.assertEqual(hub.current_tag(), "x")

    def test_unknown_saved_tag_falls_back_to_none(self):
        with open(self.state, "w") as f:
            f.write("gone")
        self.assertEqual(hub.cycle_tag(self.cfg), "")

    def test_no_tags_configured_cycles_to_nothing(self):
        self.assertEqual(hub.cycle_tag(dict(hub.DEFAULT_CONFIG, tags={})), "")

    def test_tags_with_control_characters_are_sanitised_at_load(self):
        p = os.path.join(self.tmp, "config")
        with open(p, "w") as f:
            f.write('[tags]\nhub=["to\\tols", "ok"]\n')
        cfg, _ = hub.load_config(p)
        self.assertEqual(cfg["tags"]["hub"], ["to ols", "ok"])

    def test_filtered_lines_hide_home_row_and_other_tags(self):
        a = entry("a", slug="o/a")
        b = entry("b", slug="o/b")
        lines = hub.fzf_lines([a, b], dict(self.cfg, owners=["o"]), {}, tag="y")
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("o/b\t"))

    def test_lock_is_only_removed_by_its_owner(self):
        os.makedirs(self.cache)
        lock = hub.refresh_lock()
        with mock.patch.object(hub.shutil, "which", return_value=None), \
                mock.patch.object(hub, "refresh_extra"):
            # another process's lock appears while this refresh runs: do_refresh must leave it alone
            def steal(cfg):
                with open(lock, "w") as f:
                    f.write("999999")
            hub.refresh_extra.side_effect = steal
            hub.do_refresh(dict(hub.DEFAULT_CONFIG))
        self.assertTrue(os.path.exists(lock))
        os.remove(lock)
        with mock.patch.object(hub.shutil, "which", return_value=None), mock.patch.object(hub, "refresh_extra"):
            hub.do_refresh(dict(hub.DEFAULT_CONFIG))
        self.assertFalse(os.path.exists(lock))

    def test_cache_dir_is_private(self):
        hub.ensure_cache_dir()
        self.assertEqual(os.stat(self.cache).st_mode & 0o777, 0o700)

    def test_session_dir_is_private_and_falls_back_when_path_too_long(self):
        base = os.path.join(self.tmp, "run")
        os.makedirs(base)
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": base}):
            d = hub.make_session_dir()
        self.assertTrue(d.startswith(base))
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        long = os.path.join(self.tmp, "x" * 120)
        os.makedirs(long)
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": long}), \
                mock.patch.object(hub.tempfile, "gettempdir", return_value=long):
            self.assertIsNone(hub.make_session_dir())

    def test_old_fzf_is_reported_with_the_missing_flags(self):
        help_text = "usage: fzf [options]\n --listen --header-first --track\n"
        with mock.patch.object(hub, "run", return_value=(0, help_text, "")):
            self.assertEqual(hub.fzf_missing_features(), ["--footer", "--id-nth"])
        with mock.patch.object(hub, "run", return_value=(127, "", "")):
            self.assertEqual(hub.fzf_missing_features(), [])

    def test_watcher_reloads_after_refresh_finishes_and_header_comes_first(self):
        import socketserver
        import threading
        sock = os.path.join(self.tmp, "w.sock")
        bodies = []

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                head = b""
                while not head.endswith(b"\r\n\r\n"):
                    head += self.rfile.read(1)
                n = int([l for l in head.split(b"\r\n") if l.lower().startswith(b"content-length")][0].split(b":")[1])
                if n:
                    bodies.append(self.rfile.read(n).decode())
                self.wfile.write(b"HTTP/1.0 200 OK\r\n\r\n")
        srv = socketserver.ThreadingUnixStreamServer(sock, H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)

        class Proc:
            def __init__(self):
                self.t0 = time.time()

            def poll(self):
                return None if time.time() - self.t0 < 2.0 else 0
        os.makedirs(self.cache)
        with open(hub.cache_file(), "w") as f:
            f.write("{}")
        seen = hub.cache_mtime()
        lock = hub.refresh_lock()
        open(lock, "w").close()                       # a refresh is running: no reload yet
        t = threading.Thread(target=hub.watch_refresh, args=(sock, Proc(), seen))
        t.start()
        time.sleep(0.6)
        self.assertEqual(bodies, [])
        time.sleep(0.01)
        with open(hub.cache_file(), "w") as f:        # refresh writes the cache, then drops the lock
            f.write("{}")
        os.utime(hub.cache_file(), (seen + 5, seen + 5))
        os.remove(lock)
        t.join(5)
        self.assertEqual(len(bodies), 1, bodies)
        body = bodies[0]
        self.assertLess(body.index("transform-header("), body.index("reload("))
        self.assertIn("transform-prompt(", body)           # the prompt follows the current mode


class ViewingNeverReorders(Tmp):
    """Highlighting a project used to cache its PR count, which promoted it. It must be read-only now."""

    def test_bulk_listing_carries_open_counts(self):
        payload = json.dumps([{"name": "r", "pushedAt": "2026-10-01T00:00:00Z", "isArchived": False,
                               "visibility": "PRIVATE", "description": "",
                               "pullRequests": {"totalCount": 2}, "issues": {"totalCount": 7}}])
        with mock.patch.object(hub, "run", lambda *a, **k: (0, payload, "")):
            out = hub.fetch_github(["o"])
        r = out["repos"][0]
        self.assertEqual((r["pr_count"], r["issue_count"]), (2, 7))
        self.assertNotIn("pullRequests", r)

    def test_preview_fetch_changes_neither_order_nor_main_cache(self):
        hub.save_cache_section(gh={"ok": True, "fetched_at": time.time(), "last_attempt": 1, "error": "",
                                   "repos": [{"name": "quiet", "owner": "o", "pr_count": 0},
                                             {"name": "busy", "owner": "o", "pr_count": 0}]})
        cfg = dict(hub.DEFAULT_CONFIG, pinned=[])
        es = [entry("quiet", slug="o/quiet", ts=50, gh={"name": "quiet", "owner": "o", "pr_count": 0}),
              entry("busy", slug="o/busy", ts=10, gh={"name": "busy", "owner": "o", "pr_count": 0})]
        before_order = [e["name"] for e in hub.order_entries(es, cfg)]
        before_mtime = hub.cache_mtime()

        def run(args, cwd=None, timeout=3):
            return 0, json.dumps([{"title": "a PR"}] if args[1] == "pr" else []), ""
        with mock.patch.object(hub, "run", run), mock.patch.object(hub.shutil, "which", return_value="/x/gh"):
            got = hub.fetch_prs("o/busy")
        self.assertEqual(got["pr_count"], 1)                      # the preview still shows the PR
        self.assertEqual([e["name"] for e in hub.order_entries(es, cfg)], before_order)
        self.assertEqual(hub.cache_mtime(), before_mtime)         # no reload is triggered
        self.assertIn("o/busy", hub.load_prs())


class SessionsView(Tmp):
    """Open, background, orphaned and past Claude sessions."""

    def setUp(self):
        super().setUp()
        self.cdir = os.path.join(self.tmp, "claude")
        os.makedirs(os.path.join(self.cdir, "sessions"))
        os.makedirs(os.path.join(self.cdir, "projects", "-p"))
        p = mock.patch.dict(os.environ, {"CLAUDE_HUB_CLAUDE_DIR": self.cdir,
                                         "CLAUDE_HUB_MODE_STATE": os.path.join(self.tmp, "mode.state")})
        p.start()
        self.addCleanup(p.stop)
        self.me = os.getpid()
        self.parent = os.getppid()

    def reg(self, pid, sid, **kw):
        d = {"pid": pid, "sessionId": sid, "cwd": "/work", "kind": "bg", "status": "idle", "name": sid[:6],
             "startedAt": 1_000_000, "updatedAt": 2_000_000}
        if "procStart" not in kw and hub.proc_start(pid):
            d["procStart"] = hub.proc_start(pid)
        d.update(kw)
        with open(os.path.join(self.cdir, "sessions", f"{pid}.{sid[:4]}.json"), "w") as f:
            json.dump(d, f)

    def transcript(self, sid, title="", user=True, cwd="/work", mtime=None, body=None):
        path = os.path.join(self.cdir, "projects", "-p", sid + ".jsonl")
        with open(path, "w") as f:
            if title:
                f.write(json.dumps({"type": "ai-title", "aiTitle": title, "sessionId": sid}) + "\n")
            if user:
                f.write(json.dumps({"type": "user", "cwd": cwd, "message": {"role": "user", "content": body or "hello there"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "the reply"}]}}) + "\n")
        if mtime:
            os.utime(path, (mtime, mtime))
        return path

    def states(self):
        return {s["sid"]: s["state"] for s in hub.classify_live(hub.read_registry())}

    def test_working_detached_attached_terminal_orphan_stale(self):
        self.reg(self.me, "work-0000", kind="bg", status="busy", jobId="aaaa1111")
        self.reg(self.parent, "idle-0000", kind="bg", status="idle", jobId="bbbb2222")
        self.reg(self.me + 100000, "gone-0000", kind="bg", status="idle", jobId="cccc3333", procStart="1")
        with mock.patch.object(hub, "proc_tty", return_value="/dev/pts/9"), \
                mock.patch.object(hub, "tty_alive", return_value=True):
            self.reg(self.me, "term-0000", kind="interactive", jobId=None, parkedJobId="bbbb2222")
            st = self.states()
        self.assertEqual(st["work-0000"], "working")
        self.assertEqual(st["idle-0000"], "attached")       # an interactive terminal parked it
        self.assertEqual(st["term-0000"], "terminal")
        self.assertEqual(st["gone-0000"], "stale")

    def test_interactive_without_a_terminal_is_orphaned(self):
        self.reg(self.me, "orph-0000", kind="interactive")
        with mock.patch.object(hub, "proc_tty", return_value="/dev/null"):
            self.assertEqual(self.states()["orph-0000"], "orphan")

    def test_print_mode_and_sdk_sessions_are_headless_not_orphaned(self):
        self.reg(self.me, "sdk-00000", kind="interactive", entrypoint="sdk-cli")
        with mock.patch.object(hub, "proc_tty", return_value="socket:[1]"):
            self.assertEqual(self.states()["sdk-00000"], "headless")
        self.reg(self.parent, "pm-000000", kind="interactive", entrypoint="cli")
        with mock.patch.object(hub, "proc_tty", return_value="socket:[1]"), \
                mock.patch.object(hub, "proc_cmdline", return_value="claude -p /goal run checks"):
            self.assertEqual(self.states()["pm-000000"], "headless")
        # a plain interactive cli session without a terminal is still an orphan
        self.reg(self.me, "orph-0000", kind="interactive", entrypoint="cli")
        with mock.patch.object(hub, "proc_tty", return_value="socket:[1]"), \
                mock.patch.object(hub, "proc_cmdline", return_value="claude"):
            self.assertEqual(self.states()["orph-0000"], "orphan")

    def test_pid_reuse_is_detected_by_start_time(self):
        self.reg(self.me, "reuse-000", kind="bg", procStart="12345")      # alive pid, different process
        self.assertEqual(self.states()["reuse-000"], "stale")

    def test_spare_pool_sessions_are_hidden_everywhere(self):
        self.reg(self.me, "spare-000", kind="bg", spare=True, jobId="dddd4444")
        self.transcript("spare-000", user=False)
        self.assertEqual(hub.classify_live(hub.read_registry()), [])
        self.assertEqual([s for s in hub.load_sessions() if s["sid"] == "spare-000"], [])
        self.assertNotIn("spare-000", [s["sid"] for s in hub.load_sessions()])

    def test_past_sessions_skip_blank_stubs_and_live_ones_and_sort_by_recency(self):
        self.reg(self.me, "live-0000", kind="bg", status="busy", jobId="eeee5555")
        self.transcript("live-0000", title="Live one")
        self.transcript("old-00000", title="Old work", mtime=1_000)
        self.transcript("new-00000", title="New work", mtime=5_000)
        self.transcript("stub-0000", user=False, mtime=9_000)
        names = [s["name"] for s in hub.load_sessions()]
        self.assertEqual(names[0], "live-0")                   # live first (registry name)
        self.assertEqual([n for n in names if n in ("New work", "Old work")], ["New work", "Old work"])
        self.assertNotIn("stub-000", names)
        self.assertEqual(sum(1 for s in hub.load_sessions() if s["sid"] == "live-0000"), 1)

    def test_summary_counts(self):
        self.reg(self.me, "work-0000", kind="bg", status="busy", jobId="aaaa1111")
        self.reg(self.me + 100000, "gone-0000", kind="bg", procStart="1", jobId="cccc3333")
        self.transcript("old-00000", title="Old")
        text = hub.sessions_summary()
        self.assertIn("1 working", text)
        self.assertIn("1 stale", text)
        self.assertIn("1 resumable", text)

    def test_rows_keep_the_seven_field_layout_and_carry_the_dispatch_slug(self):
        self.reg(self.me, "work-0000", kind="bg", status="busy", jobId="aaaa1111", name="Tab\tName")
        line = hub.session_lines(hub.load_sessions())[0]
        f = line.split("\t")
        self.assertEqual(len(f), 7)
        self.assertTrue(f[5].startswith("session:working:aaaa1111:"))
        self.assertTrue(f[5].endswith(":work-0000"))

    def test_preview_shows_last_prompt_and_reply(self):
        self.transcript("old-00000", title="Old work", body="please fix the thing")
        slug = "session:past::0:old-00000"
        text = hub.preview_text("/work", slug, "Old work", 60)
        self.assertIn("please fix the thing", text)
        self.assertIn("the reply", text)
        self.assertIn("enter: resume", text)

    def test_open_session_attaches_background_and_resumes_past(self):
        with mock.patch.object(hub.os, "execvp") as ex:
            hub.open_session("session:working:aaaa1111:5:work-0000", "/work")
        ex.assert_called_with("claude", ["claude", "attach", "aaaa1111"])
        d = os.path.join(self.tmp, "proj")
        os.makedirs(d)
        with mock.patch.object(hub.os, "execvp") as ex, mock.patch.object(hub.os, "chdir") as cd:
            hub.open_session("session:past::0:old-00000", d)
        cd.assert_called_with(d)
        self.assertEqual(ex.call_args[0][1][-2:], ["--resume", "old-00000"])

    def test_resume_with_missing_directory_falls_back_to_home(self):
        with mock.patch.object(hub.os, "execvp"), mock.patch.object(hub.os, "chdir") as cd:
            hub.open_session("session:past::0:old-00000", "/definitely/not/here")
        cd.assert_called_with(hub.HOME)

    def test_terminal_and_orphan_rows_explain_instead_of_launching(self):
        with self.assertRaises(SystemExit) as cm:
            hub.open_session("session:terminal::5:x", "/work")
        self.assertIn("another terminal", str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            hub.open_session("session:orphan::5:x", "/work")
        self.assertIn("ctrl-x", str(cm.exception))

    def test_stop_removes_a_stale_entry_only_after_confirmation(self):
        self.reg(self.me + 100000, "gone-0000", kind="bg", procStart="1", jobId="cccc3333")
        slug = f"session:stale:cccc3333:{self.me + 100000}:gone-0000"
        files = glob.glob(os.path.join(self.cdir, "sessions", "*.json"))
        self.assertEqual(len(files), 1)
        with mock.patch("builtins.input", return_value="n"):
            hub.session_stop(slug)
        self.assertTrue(os.path.exists(files[0]))
        with mock.patch("builtins.input", return_value="y"), mock.patch.object(hub.time, "sleep"):
            hub.session_stop(slug)
        self.assertFalse(os.path.exists(files[0]))

    def test_stop_signals_an_orphan_only_when_pid_and_registry_agree(self):
        self.reg(self.me, "orph-0000", kind="interactive")
        slug = f"session:orphan::{self.me}:orph-0000"
        with mock.patch.object(hub, "proc_tty", return_value="/dev/null"), \
                mock.patch("builtins.input", return_value="y"), mock.patch.object(hub.time, "sleep"), \
                mock.patch.object(hub.os, "kill") as kill:
            hub.session_stop(slug)
            kill.assert_called_once_with(self.me, hub.signal.SIGTERM)
        with mock.patch.object(hub, "proc_tty", return_value="/dev/null"), \
                mock.patch("builtins.input", return_value="y"), mock.patch.object(hub.time, "sleep"), \
                mock.patch.object(hub.os, "kill") as kill:
            hub.session_stop(f"session:orphan::{self.me + 1}:orph-0000")   # pid does not match the registry
            kill.assert_not_called()

    def test_stop_on_a_project_row_does_nothing_and_never_prompts(self):
        with mock.patch("builtins.input", side_effect=AssertionError("no prompt expected")):
            self.assertEqual(hub.session_stop("jdk-official/claude-hub"), 0)

    def test_mode_toggle(self):
        self.assertEqual(hub.current_mode(), "projects")
        self.assertEqual(hub.toggle_mode(), "sessions")
        self.assertEqual(hub.current_mode(), "sessions")
        self.assertEqual(hub.toggle_mode(), "projects")

    def test_tail_extracts_last_prompt_and_reply(self):
        path = self.transcript("t-0000000", body="first question")
        with open(path, "a") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "second question"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "second answer"}]}}) + "\n")
        self.assertEqual(hub.transcript_tail(path), ("second question", "second answer"))


class WorktreesBadgesBulk(Tmp):
    def mk_repo_with_worktree(self, remote="git@github.com:o/proj.git"):
        root = os.path.join(self.tmp, "root")
        os.makedirs(root)
        parent = os.path.join(root, "proj")
        make_repo(parent, remote=remote)
        wt = os.path.join(root, "proj-feature")
        sh(["git", "worktree", "add", "-q", "-b", "feature", wt], parent)
        return root, parent, wt

    # --- worktrees -------------------------------------------------------
    def test_worktree_is_detected_from_the_git_file(self):
        root, parent, wt = self.mk_repo_with_worktree()
        self.assertEqual(hub.inspect_dir(root, wt)["worktree_of"], os.path.realpath(parent))
        self.assertEqual(hub.inspect_dir(root, parent)["worktree_of"], "")

    def test_worktree_shares_the_remote_but_is_not_deduplicated_away(self):
        root, parent, wt = self.mk_repo_with_worktree()
        es = hub.build_entries(hub.scan_local([root]), [], dict(hub.DEFAULT_CONFIG))
        self.assertEqual(sorted(e["name"] for e in es), ["proj", "proj-feature"])
        child = next(e for e in es if e["name"] == "proj-feature")
        self.assertEqual(child["parent"], parent)

    def test_worktrees_sit_under_their_parent_and_parent_inherits_recency(self):
        root, parent, wt = self.mk_repo_with_worktree()
        other = os.path.join(root, "zzz-other")
        make_repo(other, remote="git@github.com:o/other.git", date="2026-10-13T12:00:00")
        local = hub.scan_local([root])
        for l in local:                        # the worktree is the most recently active place
            l["ts"] = {"proj-feature": 9000, "proj": 10, "zzz-other": 500}[l["name"]]
        cfg = dict(hub.DEFAULT_CONFIG)
        es = hub.group_worktrees(hub.order_entries(hub.build_entries(local, [], cfg), cfg))
        self.assertEqual([e["name"] for e in es], ["proj", "proj-feature", "zzz-other"])

    def test_dirty_worktree_makes_the_parent_needs_attention(self):
        root, parent, wt = self.mk_repo_with_worktree()
        with open(os.path.join(wt, "wip.txt"), "w") as f:
            f.write("x")
        cfg = dict(hub.DEFAULT_CONFIG)
        es = hub.build_entries(hub.scan_local([root]), [], cfg)
        p = next(e for e in es if e["name"] == "proj")
        self.assertTrue(hub.needs_attention(p, None))
        self.assertIn("⎇1", hub.markers(p, cfg))

    def test_rows_indent_worktrees(self):
        root, parent, wt = self.mk_repo_with_worktree()
        cfg = dict(hub.DEFAULT_CONFIG, show_worktrees=True)
        es = hub.group_worktrees(hub.order_entries(hub.build_entries(hub.scan_local([root]), [], cfg), cfg))
        lines = hub.fzf_lines(es, cfg, {})
        names = [l.split("\t")[1].strip() for l in lines[1:]]
        self.assertEqual(names, ["↳ proj-feature"])     # proj has someone else's remote, so it is on the Other tab
        self.assertEqual([l.split("\t")[1].strip() for l in hub.fzf_lines(es, cfg, {}, tab="other")][1:], ["◇ proj"])
        cfg = dict(cfg, owners=["o"])
        lines = hub.fzf_lines(es, cfg, {})
        names = [l.split("\t")[1].strip() for l in lines[1:]]
        self.assertEqual(names, ["⌂ proj", "↳ proj-feature"])   # once the owner is yours, proj is a project
        self.assertEqual(lines[2].split("\t")[6], "proj-feature")      # the raw name is still what launches

    def test_preview_lists_other_worktrees(self):
        root, parent, wt = self.mk_repo_with_worktree()
        with mock.patch.object(hub, "live_sessions", return_value=[]):
            text = hub.preview_text(parent, "", "proj", 60)
        self.assertIn("worktrees:", text)
        self.assertIn("proj-feature", text)

    # --- session badges ---------------------------------------------------
    def entry_for(self, path, name):
        l = {"name": name, "path": path, "root": os.path.dirname(path), "is_git": True, "ts": 1, "branch": "main",
             "dirty": 0, "ahead": 0, "behind": 0, "has_upstream": False, "remote": "", "slug": "", "worktree_of": ""}
        return {"name": name, "slug": "", "path": path, "local": l, "gh": None, "ts": 1, "origin": "x"}

    def test_badges_use_the_most_specific_directory_and_count_home(self):
        a = self.entry_for("/work/proj", "proj")
        b = self.entry_for("/work/proj/sub", "sub")
        sess = [{"cwd": "/work/proj/x/deep", "state": "working"}, {"cwd": "/work/proj/sub", "state": "detached"},
                {"cwd": hub.HOME, "state": "terminal"}, {"cwd": hub.HOME, "state": "orphan"},
                {"cwd": "/elsewhere", "state": "working"}]
        with mock.patch.object(hub.os.path, "realpath", side_effect=lambda p: p):
            home = hub.attach_session_badges([a, b], sess)
        self.assertEqual(a["sess"]["n"], 1)
        self.assertEqual(b["sess"]["n"], 1)
        self.assertEqual(home, {"n": 2, "orphan": 1})
        self.assertIn("▶1", hub.markers(a, hub.DEFAULT_CONFIG))

    def test_badges_never_change_the_order(self):
        quiet = self.entry_for("/work/quiet", "quiet")
        quiet["ts"] = 50
        busy = self.entry_for("/work/busy", "busy")
        busy["ts"] = 10
        before = [e["name"] for e in hub.order_entries([busy, quiet], hub.DEFAULT_CONFIG)]
        with mock.patch.object(hub.os.path, "realpath", side_effect=lambda p: p):
            hub.attach_session_badges([busy, quiet], [{"cwd": "/work/busy", "state": "working"}])
        self.assertEqual([e["name"] for e in hub.order_entries([busy, quiet], hub.DEFAULT_CONFIG)], before)

    def test_home_row_shows_the_badge(self):
        cache = {"_home_sessions": {"n": 3, "orphan": 1}}
        line = hub.fzf_lines([], hub.DEFAULT_CONFIG, cache)[0]
        self.assertIn("▶3", line)
        self.assertIn("⚠1", line)

    # --- bulk lines ---------------------------------------------------------
    def test_bulk_commits_count_as_commits_but_their_lines_are_separate(self):
        commits = [{"hash": "a", "date": "2026-10-13", "ins": 54000, "del": 800},
                   {"hash": "b", "date": "2026-10-13", "ins": 120, "del": 30},
                   {"hash": "c", "date": "2026-10-13", "ins": 10, "del": 0}]
        st = hub.aggregate({"/r": ("r", commits)})
        day = st["days"]["2026-10-13"]
        self.assertEqual(day["c"], 3)
        self.assertEqual((day["ins"], day["del"]), (130, 30))
        self.assertEqual((day["bulk_ins"], day["bulk_del"]), (54000, 800))

    def test_header_reports_bulk_separately(self):
        from datetime import date as D
        days = {"2026-10-13": {"c": 3, "ins": 130, "del": 30, "bulk_ins": 54000, "bulk_del": 800, "repos": ["r"]}}
        lines = hub.stats_header({"stats": {"days": days}}, today=D(2026, 10, 13))
        self.assertIn("+130/-30 (+54.8k bulk)", lines[0])
        self.assertIn("(+54.8k bulk)", lines[1])

    def test_header_without_bulk_is_unchanged(self):
        from datetime import date as D
        days = {"2026-10-13": {"c": 1, "ins": 5, "del": 1, "repos": ["r"]}}
        self.assertNotIn("bulk", hub.stats_header({"stats": {"days": days}}, today=D(2026, 10, 13))[0])


class SourceTabs(Tmp):
    """Source glyphs, honest origin labels, and tabs (feature set from the 'where does this live' brainstorm)."""

    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.tmp, "mode.state")
        p = mock.patch.dict(os.environ, {"CLAUDE_HUB_MODE_STATE": self.state})
        p.start()
        self.addCleanup(p.stop)
        self.cfg = dict(hub.DEFAULT_CONFIG, owners=["me"])

    def e(self, name, kind, remote_owner="", root="/mnt/data/github", parent=False):
        l = None
        g = None
        if kind in ("synced", "local", "other-owner", "folder", "worktree"):
            l = {"name": name, "path": f"{root}/{name}", "root": root, "is_git": kind != "folder", "ts": 1,
                 "branch": "main", "dirty": 0, "ahead": 0, "behind": 0, "has_upstream": False, "remote": "",
                 "slug": f"{remote_owner}/{name}" if remote_owner else "", "worktree_of": ""}
        if kind in ("synced", "github"):
            g = {"name": name, "owner": "me", "pr_count": 0}
        e = {"name": name, "slug": f"me/{name}" if g else (l or {}).get("slug", ""), "path": l["path"] if l else "",
             "local": l, "gh": g, "ts": 1, "origin": "x"}
        if parent:
            e["parent"] = "/p"
        return e

    def test_source_kinds(self):
        c = self.cfg
        self.assertEqual(hub.source_kind(self.e("a", "synced"), c), "synced")
        self.assertEqual(hub.source_kind(self.e("b", "github"), c), "github")
        self.assertEqual(hub.source_kind(self.e("c", "local"), c), "local")
        self.assertEqual(hub.source_kind(self.e("d", "folder"), c), "folder")
        self.assertEqual(hub.source_kind(self.e("e", "other-owner", remote_owner="them"), c), "other-owner")
        self.assertEqual(hub.source_kind(self.e("f", "local", remote_owner="me"), c), "local")
        self.assertEqual(hub.source_kind(self.e("w", "worktree", parent=True), c), "worktree")

    def test_projects_tab_merges_local_and_github_and_other_holds_the_rest(self):
        c = self.cfg
        synced, gh_only = self.e("a", "synced"), self.e("b", "github")
        local, folder = self.e("c", "local"), self.e("d", "folder")
        theirs = self.e("e", "other-owner", remote_owner="them")
        wt = self.e("w", "worktree", parent=True)
        member = lambda e: {t for t in hub.TABS if hub.in_tab(e, c, t)}
        for e in (synced, gh_only, local, wt):
            self.assertEqual(member(e), {"projects"})
        for e in (folder, theirs):
            self.assertEqual(member(e), {"other"})

    def test_counts_and_bar_mark_the_current_tab(self):
        es = [self.e("a", "synced"), self.e("b", "github"), self.e("c", "local"), self.e("d", "folder")]
        bar = hub.tab_bar(es, self.cfg, "projects", sessions_n=3)
        self.assertEqual(bar, "◂ [Projects 3] · Other 1 · Sessions 3 ▸")

    def test_rows_start_with_the_source_glyph(self):
        c = self.cfg
        cells = lambda e: hub.row_cells(e, c)[0]
        self.assertEqual(cells(self.e("a", "synced")), "◆ a")
        self.assertEqual(cells(self.e("b", "github")), "◌ b")
        self.assertEqual(cells(self.e("c", "local")), "⌂ c")
        self.assertEqual(cells(self.e("d", "folder")), "▫ d")
        self.assertEqual(cells(self.e("e", "other-owner", remote_owner="them")), "◇ e")
        self.assertEqual(cells(self.e("w", "worktree", parent=True)), "↳ w")

    def test_origin_labels_never_use_a_bare_folder_name(self):
        base = {"root": hub.CLONE_ROOT, "slug": "", "path": hub.CLONE_ROOT + "/x"}
        self.assertEqual(hub.origin_label(base), "local")
        self.assertEqual(hub.origin_label(dict(base, root="/mnt/data/scratch")), "dir:scratch")
        self.assertEqual(hub.origin_label(dict(base, slug="winboat-org/helios")), "gh:winboat-org")

    def test_tab_filtering_in_the_list(self):
        es = [self.e("a", "synced"), self.e("b", "github"), self.e("c", "local"), self.e("d", "folder")]
        names = lambda tab: [l.split("\t")[6] for l in hub.fzf_lines(es, self.cfg, {}, "", tab) if not l.startswith("~")]
        self.assertEqual(names("projects"), ["a", "b", "c"])
        self.assertEqual(names("other"), ["d"])

    def test_home_row_only_on_projects(self):
        has_home = lambda tab: any(l.startswith("~\t") for l in hub.fzf_lines([], self.cfg, {}, "", tab))
        self.assertTrue(has_home("projects"))
        self.assertFalse(has_home("other"))

    def test_tab_stepping_wraps_and_jumps(self):
        self.assertEqual(hub.current_tab(), "projects")
        self.assertEqual([hub.step_tab("next") for _ in range(3)], ["other", "sessions", "projects"])
        self.assertEqual(hub.step_tab("prev"), "sessions")
        self.assertEqual(hub.step_tab("2"), "other")
        self.assertEqual(hub.step_tab("99"), "sessions")      # clamped, not an error
        self.assertEqual(hub.step_tab("nonsense"), "sessions")
        self.assertEqual(hub.current_mode(), "sessions")

    def test_old_state_values_are_understood(self):
        for old in ("projects", "all", "local", "github"):
            with open(self.state, "w") as f:
                f.write(old)
            self.assertEqual(hub.current_tab(), "projects")

    def test_long_state_text_is_capped_so_the_origin_stays_visible(self):
        e = self.e("a", "local")
        e["local"]["branch"] = "pbi/019-a-very-long-branch-name-that-would-push-everything-off"
        cells = hub.row_cells(e, self.cfg)
        self.assertLessEqual(len(cells[4]), hub.STATE_MAX)      # columns: name, markers, age, origin, state
        self.assertTrue(cells[4].endswith("…"))
        self.assertEqual(cells[3], e["origin"])

    def test_origin_column_is_dropped_when_the_other_tab_is_uniform(self):
        es = [self.e("a", "folder"), self.e("c", "folder")]
        for e in es:
            e["origin"] = "dir:scratch"
        self.assertNotIn("dir:scratch", hub.fzf_lines(es, self.cfg, {}, "", "other")[0])
        es[1]["origin"] = "dir:files"
        self.assertIn("dir:scratch", "\n".join(hub.fzf_lines(es, self.cfg, {}, "", "other")))

    def test_long_worktree_names_drop_the_parent_prefix_and_are_capped(self):
        wt = self.e("claude-code-terminal-bar-crawl-pbi-014-ci-for-the-public-repo", "worktree", parent=True)
        wt["parent"] = "/mnt/data/github/claude-code-terminal-bar-crawl"
        self.assertEqual(hub.display_name(wt), "pbi-014-ci-for-the-public-repo")
        self.assertEqual(wt["name"].startswith("claude-code"), True)          # the real name is untouched
        short_wt = self.e("alpha-feature", "worktree", parent=True)
        short_wt["parent"] = "/p/alpha"
        self.assertEqual(hub.display_name(short_wt), "alpha-feature")         # short names are left alone
        huge = self.e("x" * 60, "local")
        self.assertEqual(len(hub.display_name(huge)), hub.NAME_MAX)
        self.assertTrue(hub.display_name(huge).endswith("…"))

    def test_empty_tabs_get_one_inert_placeholder_row(self):
        for tab, text in (("other", "nothing in the Other tab"), ("sessions", "(no sessions)")):
            rows = hub.ensure_rows([], tab)
            self.assertEqual(len(rows), 1)
            fields = rows[0].split("\t")
            self.assertEqual(len(fields), 7)
            self.assertEqual(fields[0], hub.EMPTY_ID)
            self.assertIn(text, fields[1])
        self.assertEqual(hub.ensure_rows(["a\tb"], "all"), ["a\tb"])

    def test_start_tab_config(self):
        p = os.path.join(self.tmp, "config")
        with open(p, "w") as f:
            f.write('start_tab = "Other"\n')
        self.assertEqual(hub.load_config(p)[0]["start_tab"], "other")
        for old in ("all", "local", "github"):          # earlier tab names mean Projects, without a warning
            with open(p, "w") as f:
                f.write(f'start_tab = "{old}"\n')
            cfg, warn = hub.load_config(p)
            self.assertEqual((cfg["start_tab"], warn), ("projects", None))
        with open(p, "w") as f:
            f.write('start_tab = "nowhere"\n')
        cfg, warn = hub.load_config(p)
        self.assertEqual(cfg["start_tab"], "projects")
        self.assertIn("start_tab", warn)


class TabDashboards(Tmp):
    """The summary rows that lead the Other and Sessions tabs."""

    def sess(self, state, name="s", updated=None, cwd="/w"):
        return {"sid": name + "-id", "job": "j", "name": name, "cwd": cwd, "kind": "bg", "state": state,
                "status": "", "pid": 1, "tty": "", "updated": updated if updated is not None else time.time(), "file": ""}

    def test_needs_you_counts_orphans_stale_and_forgotten_detached(self):
        now = 10 * 86400
        ss = [self.sess("orphan", "o"), self.sess("stale", "x"), self.sess("detached", "forgotten", updated=now - 2 * 86400),
              self.sess("detached", "fresh", updated=now - 3600), self.sess("working", "w"), self.sess("terminal", "t")]
        got = hub.needs_you(ss, now)
        self.assertEqual([s["name"] for s, _, _ in got], ["o", "x", "forgotten"])

    def test_sessions_summary_row_and_dashboard(self):
        none = hub.sessions_summary_row([self.sess("working")])
        self.assertIn("nothing needs you", none)
        ss = [self.sess("orphan", "lost"), self.sess("working", "busy")]
        row = hub.sessions_summary_row(ss).split("\t")
        self.assertEqual((len(row), row[0]), (7, hub.NEEDS_ID))
        self.assertIn("needs you  1", row[1])
        text = hub.sessions_dashboard_text(60, ss)
        self.assertIn("1 to deal with", text)
        self.assertIn("lost", text)
        self.assertIn("ctrl-x stops it", text)
        self.assertNotIn("busy", text.split("sessions:")[0])        # healthy sessions are not listed as problems
        self.assertIn("Nothing to clean up", hub.sessions_dashboard_text(60, [self.sess("working")]))

    def test_sessions_tab_always_leads_with_the_summary_row(self):
        self.assertEqual(hub.sessions_tab_lines([])[0].split("\t")[0], hub.NEEDS_ID)
        self.assertEqual(len(hub.sessions_tab_lines([self.sess("working")])), 2)

    def other(self, name, days, dirty=0, kind="folder"):
        now = 1_000_000_000
        l = {"name": name, "path": f"/x/{name}", "root": "/x", "is_git": kind != "folder", "ts": now - days * 86400,
             "branch": "main", "dirty": dirty, "ahead": 0, "behind": 0, "has_upstream": False, "remote": "",
             "slug": "them/" + name if kind != "folder" else "", "worktree_of": ""}
        return {"name": name, "slug": l["slug"], "path": l["path"], "local": l, "gh": None, "ts": l["ts"], "origin": "dir:x"}

    def test_stale_entries_are_old_other_items_oldest_first(self):
        cfg = dict(hub.DEFAULT_CONFIG, owners=["me"])
        now = 1_000_000_000
        es = [self.other("fresh", 5), self.other("old", 100), self.other("oldest", 400),
              self.other("theirs-old", 200, kind="git")]
        got = [e["name"] for e in hub.stale_entries(es, cfg, now)]
        self.assertEqual(got, ["oldest", "theirs-old", "old"])

    def test_other_dashboard_flags_unsaved_work_and_offers_a_hidden_line(self):
        cfg = dict(hub.DEFAULT_CONFIG, owners=["me"])
        now = 1_000_000_000
        es = [self.other("a", 120, dirty=3), self.other("b", 130), self.other("c", 1)]
        text = hub.other_dashboard_text(80, es, cfg, now)
        self.assertIn("2 untouched for 90 days", text)
        self.assertIn("●3", text)
        self.assertIn('hidden = ["b", "a"]', text)
        self.assertNotIn("hidden", hub.other_dashboard_text(80, [self.other("c", 1)], cfg, now))

    def test_other_tab_leads_with_the_stale_row_only_when_it_has_entries(self):
        cfg = dict(hub.DEFAULT_CONFIG, owners=["me"])
        lines = hub.fzf_lines([self.other("a", 1)], cfg, {}, "", "other")
        self.assertEqual(lines[0].split("\t")[0], hub.STALE_ID)
        self.assertEqual(hub.fzf_lines([], cfg, {}, "", "other"), [])
        self.assertTrue(all(not l.startswith(hub.STALE_ID) for l in hub.fzf_lines([self.other("a", 1)], cfg, {}, "", "projects")))

    def test_preview_routes_the_summary_rows(self):
        with mock.patch.object(hub, "sessions_dashboard_text", return_value="S"), \
                mock.patch.object(hub, "other_dashboard_text", return_value="O"):
            self.assertEqual(hub.preview_text("", "", hub.NEEDS_ID), "S")
            self.assertEqual(hub.preview_text("", "", hub.STALE_ID), "O")


class SessionLegend(Tmp):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"CLAUDE_HUB_MODE_STATE": os.path.join(self.tmp, "mode.state"),
                                         "CLAUDE_HUB_CLAUDE_DIR": os.path.join(self.tmp, "claude")})
        p.start()
        self.addCleanup(p.stop)

    def test_legend_names_every_state_with_its_own_glyph(self):
        text = hub.session_legend()
        for state, glyph in hub.SESSION_GLYPH.items():
            self.assertIn(f"{glyph} {state}", text)
        self.assertEqual(set(hub.SESSION_LEGEND_ORDER), set(hub.SESSION_GLYPH))

    def test_legend_lines_each_fit_a_narrow_pane(self):
        lines = hub.session_legend_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(len(l) <= 44 for l in lines), lines)
        self.assertEqual(" ".join(lines), hub.session_legend())

    def test_session_rows_lead_with_the_state_glyph(self):
        s = {"sid": "s-1", "job": "j", "name": "My session", "cwd": "/w", "kind": "bg", "state": "orphan",
             "status": "", "pid": 5, "tty": "", "updated": 1, "file": ""}
        f = hub.session_lines([s])[0].split("\t")
        self.assertTrue(f[1].startswith("⚠ My session"))
        self.assertEqual(f[6], "My session")                      # the raw name is untouched

    def test_legend_is_in_the_header_only_on_the_sessions_tab(self):
        cfg = dict(hub.DEFAULT_CONFIG)
        hub.set_tab("projects")
        self.assertNotIn(hub.session_legend_lines()[0], "\n".join(hub.header_lines({}, cfg, None, False, [])))
        hub.set_tab("sessions")
        header = hub.header_lines({}, cfg, None, False, [])
        for line in hub.session_legend_lines():
            self.assertIn(line, header)
        self.assertTrue(header[0].startswith("◂"))                                  # the tab bar leads
        self.assertLess(header.index(hub.session_legend_lines()[0]), len(header))

    def test_legend_is_on_the_dashboard(self):
        hub.save_cache_section(stats={"computed_at": 1, "days": {}, "repo_weeks": {}, "partial": 0})
        with mock.patch.object(hub, "CACHE_DIR", self.cache):
            self.assertIn("⚠ orphan", hub.dashboard_text(200))

    def test_text_list_ends_with_the_legend(self):
        r = subprocess.run([sys.executable, HUB, "sessions"], capture_output=True, text=True,
                           env=dict(os.environ, HOME=self.tmp, CLAUDE_HUB_CACHE_DIR=self.cache))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], hub.session_legend())


class UxReview(Tmp):
    """The review round: ages, collapsed worktrees, header, help, supported listing, resume by id, rm."""

    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {
            "CLAUDE_HUB_MODE_STATE": os.path.join(self.tmp, "mode.state"),
            "CLAUDE_HUB_WT_STATE": os.path.join(self.tmp, "wt.state"),
            "CLAUDE_HUB_TAG_STATE": os.path.join(self.tmp, "tag.state"),
            "CLAUDE_HUB_CLAUDE_DIR": os.path.join(self.tmp, "claude")})
        p.start()
        self.addCleanup(p.stop)
        self.cfg = dict(hub.DEFAULT_CONFIG)
        os.makedirs(os.path.join(self.tmp, "claude", "sessions"))

    # --- ages
    def test_age_resolves_inside_a_day(self):
        now = 1_000_000.0
        a = lambda secs: hub.age(now - secs, now)
        self.assertEqual(a(20), "just now")
        self.assertEqual(a(10 * 60), "10m ago")
        self.assertEqual(a(3 * 3600 + 60), "3h ago")
        self.assertEqual(a(26 * 3600), "1d ago")
        self.assertEqual(a(20 * 86400), "2w ago")

    # --- worktrees collapsed by default, ctrl-w toggles
    def _entries(self):
        def mk(name, parent=None):
            l = {"name": name, "path": "/p/" + name, "root": "/p", "is_git": True, "ts": 1, "branch": "main", "dirty": 0,
                 "ahead": 0, "behind": 0, "has_upstream": False, "remote": "", "slug": "", "worktree_of": parent or ""}
            e = {"name": name, "slug": "", "path": l["path"], "local": l, "gh": None, "ts": 1, "origin": "local"}
            if parent:
                e["parent"] = parent
            return e
        return [mk("proj"), mk("proj-feature", "/p/proj"), mk("other")]

    def test_worktrees_are_collapsed_until_toggled(self):
        es = self._entries()
        names = lambda: [l.split("\t")[6] for l in hub.fzf_lines(es, self.cfg, {}) if not l.startswith("~\t")]
        self.assertEqual(names(), ["proj", "other"])
        self.assertTrue(hub.toggle_worktrees(self.cfg))
        self.assertEqual(names(), ["proj", "proj-feature", "other"])
        self.assertFalse(hub.toggle_worktrees(self.cfg))
        self.assertEqual(names(), ["proj", "other"])

    def test_counts_and_header_hint_follow_the_collapsed_state(self):
        es = self._entries()
        self.assertIn("Projects 2", hub.tab_bar(es, self.cfg, "projects", sessions_n=0))
        hub.set_tab("projects")
        header = hub.header_lines({}, self.cfg, None, False, es)
        self.assertTrue(any("1 worktrees collapsed" in l and "ctrl-w" in l for l in header))
        hub.toggle_worktrees(self.cfg)
        self.assertIn("Projects 3", hub.tab_bar(es, self.cfg, "projects", sessions_n=0))
        self.assertFalse(any("collapsed" in l for l in hub.header_lines({}, self.cfg, None, False, es)))

    def test_show_worktrees_config(self):
        p = os.path.join(self.tmp, "config")
        with open(p, "w") as f:
            f.write("show_worktrees = true\n")
        cfg, _ = hub.load_config(p)
        self.assertTrue(hub.worktrees_shown(cfg))
        with open(p, "w") as f:
            f.write('show_worktrees = "yes"\n')
        cfg, warn = hub.load_config(p)
        self.assertFalse(cfg["show_worktrees"])
        self.assertIn("show_worktrees", warn)

    # --- header
    def test_header_has_the_tab_bar_first_and_no_statistics_line(self):
        days = {"2026-10-13": {"c": 2, "ins": 1500, "del": 20, "bulk_ins": 54000, "bulk_del": 800, "repos": ["a"]}}
        header = hub.header_lines({"stats": {"days": days}}, self.cfg, None, False, [])
        self.assertTrue(header[0].startswith("◂"))
        self.assertFalse(any(l.startswith("streak") or "bulk" in l for l in header))   # lives on the dashboard
        self.assertFalse(any(l.startswith("sessions:") for l in header))               # only on the Sessions tab
        self.assertFalse(any(l.startswith("stats:") for l in header))

    def test_dashboard_still_has_the_streak_today_and_week(self):
        from datetime import date as D
        days = {"2026-10-13": {"c": 2, "ins": 1500, "del": 20, "bulk_ins": 54000, "bulk_del": 800, "repos": ["a"]}}
        text = "\n".join(hub.stats_lines_compact({"stats": {"days": days}}, today=D(2026, 10, 13)))
        self.assertIn("streak 1d", text)
        self.assertIn("today 2c", text)
        self.assertIn("week  2c", text)
        self.assertIn("(+54.8k bulk)", text)

    def test_computing_copy_no_longer_says_next_launch(self):
        self.assertNotIn("next launch", hub.stats_header({})[0])
        self.assertNotIn("next launch", hub.dashboard_text(60))

    def test_help_text_has_keys_and_both_glyph_keys(self):
        for needle in ("ctrl-l", "ctrl-w", "alt-h", "◆ local + GitHub", "◌ GitHub only", "▶ working", "⚠ orphan",
                       "headless"):
            self.assertIn(needle, hub.HELP_TEXT)

    def test_help_and_dashboard_lines_fit_a_narrow_preview(self):
        for line in hub.HELP_TEXT.splitlines():
            self.assertLessEqual(len(line), 44, line)
        days = {"2026-10-13": {"c": 126, "ins": 35300, "del": 6900, "bulk_ins": 223300, "bulk_del": 0, "repos": list("abcdef")}}
        from datetime import date as D
        for line in hub.stats_lines_compact({"stats": {"days": days}}, today=D(2026, 10, 13)):
            self.assertLessEqual(len(line), 44, line)

    # --- supported listing
    def test_fetch_agents_parses_and_filters(self):
        payload = json.dumps([{"sessionId": "s1", "pid": "5", "name": "A"}, {"nope": 1}, "junk"])
        with mock.patch.dict(os.environ, {"CLAUDE_HUB_NO_AGENTS": ""}), \
                mock.patch.object(hub.shutil, "which", return_value="/x/claude"), \
                mock.patch.object(hub, "run", return_value=(0, payload, "")):
            hub._AGENTS_MEMO[0] = 0
            self.assertEqual([a["sessionId"] for a in hub.fetch_agents()], ["s1"])

    def test_fetch_agents_is_empty_when_it_fails_or_is_switched_off(self):
        with mock.patch.dict(os.environ, {"CLAUDE_HUB_NO_AGENTS": ""}), \
                mock.patch.object(hub.shutil, "which", return_value="/x/claude"), \
                mock.patch.object(hub, "run", return_value=(1, "", "boom")):
            hub._AGENTS_MEMO[0] = 0
            self.assertEqual(hub.fetch_agents(), [])
        with mock.patch.dict(os.environ, {"CLAUDE_HUB_NO_AGENTS": "1"}):
            hub._AGENTS_MEMO[0] = 0
            self.assertEqual(hub.fetch_agents(), [])

    def test_merge_adds_running_sessions_the_registry_missed_and_prefers_the_listing_name(self):
        me = os.getpid()
        reg = [{"pid": me, "sessionId": "known-0000", "name": "old name", "kind": "bg", "cwd": "/w", "jobId": "j1"}]
        agents = [{"sessionId": "known-0000", "name": "fresh name", "pid": str(me)},
                  {"sessionId": "new-00000", "name": "Only in listing", "pid": str(me), "kind": "background",
                   "id": "j2", "cwd": "/x", "status": "idle"},
                  {"sessionId": "past-0000", "name": "no process", "pid": "", "kind": "background"}]
        merged = {e["sessionId"]: e for e in hub.merge_agents(reg, agents)}
        self.assertEqual(merged["known-0000"]["name"], "fresh name")
        self.assertEqual(merged["new-00000"]["jobId"], "j2")
        self.assertNotIn("past-0000", merged)

    def test_sessions_work_from_the_listing_alone_if_the_registry_changes_shape(self):
        me = os.getpid()
        agents = [{"sessionId": "only-0000", "name": "Listed", "pid": str(me), "kind": "background", "id": "jj",
                   "cwd": "/w", "status": "busy"}]
        with mock.patch.dict(os.environ, {"CLAUDE_HUB_NO_AGENTS": ""}), \
                mock.patch.object(hub.shutil, "which", return_value="/x/claude"), \
                mock.patch.object(hub, "run", return_value=(0, json.dumps(agents), "")):
            hub._AGENTS_MEMO[0] = 0
            states = {s["sid"]: s["state"] for s in hub.current_sessions()}
        self.assertEqual(states["only-0000"], "working")

    # --- ctrl-l resolves to an exact session
    def sess(self, sid, state, cwd="/w/proj", updated=100, job=""):
        return {"sid": sid, "job": job, "name": sid, "cwd": cwd, "kind": "bg", "state": state, "status": "",
                "pid": 1, "tty": "", "updated": updated, "file": ""}

    def test_resolve_prefers_the_most_recent_resumable_session(self):
        ss = [self.sess("old", "past", updated=10), self.sess("new", "past", updated=50),
              self.sess("term", "terminal", updated=99), self.sess("elsewhere", "past", cwd="/other", updated=200)]
        kind, ident, _ = hub.resolve_resume("/w/proj", ss)
        self.assertEqual((kind, ident), ("resume", "new"))      # the terminal-held and other-project ones are skipped

    def test_resolve_attaches_a_running_background_session(self):
        ss = [self.sess("bg", "detached", updated=90, job="jobX"), self.sess("past", "past", updated=10)]
        self.assertEqual(hub.resolve_resume("/w/proj", ss)[:2], ("attach", "jobX"))

    def test_resolve_with_no_history_starts_new(self):
        self.assertEqual(hub.resolve_resume("/w/proj", [])[0], "new")

    def test_continue_last_execs_resume_by_id_in_the_project(self):
        d = os.path.join(self.tmp, "proj")
        os.makedirs(d)
        ss = [self.sess("abc-123", "past", cwd=d, updated=time.time() - 60)]
        with mock.patch.object(hub, "load_sessions", return_value=ss), \
                mock.patch.object(hub.os, "execvp") as ex, mock.patch.object(hub.os, "chdir") as cd:
            hub.continue_last(d)
        cd.assert_called_with(d)
        self.assertEqual(ex.call_args[0][1], ["claude", "--resume", "abc-123"])

    def test_preview_states_what_ctrl_l_will_do(self):
        d = os.path.join(self.tmp, "proj")
        os.makedirs(d)
        sh(["git", "init", "-q", "-b", "main"], d)
        ss = [self.sess("abc-123", "past", cwd=d, updated=time.time() - 60)]
        ss[0]["name"] = "Fix the login bug"
        with mock.patch.object(hub, "load_sessions", return_value=ss), mock.patch.object(hub, "live_sessions", return_value=[]):
            text = hub.preview_text(d, "", "proj", 80)
        self.assertIn("ctrl-l resumes: Fix the login bug", text)

    # --- rm for idle background sessions
    def test_stop_uses_rm_for_idle_and_stop_for_working(self):
        calls = []

        def fake_run(args, **kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0)
        entry = {"sid": "s", "state": "x"}
        with mock.patch("builtins.input", return_value="y"), mock.patch.object(hub.time, "sleep"), \
                mock.patch.object(hub.subprocess, "run", side_effect=fake_run):
            hub.session_stop("session:detached:jobA:5:s")
            hub.session_stop("session:working:jobB:5:s")
        self.assertEqual(calls, [["claude", "rm", "jobA"], ["claude", "stop", "jobB"]])


if __name__ == "__main__":
    unittest.main()
