"""Tests for bin/hub. Run: python3 -m unittest discover -s tests -v"""
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
HUB = os.path.join(ROOT, "bin", "hub")


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
        self.assertIn("cached 5m", f({"gh": {"ok": True, "fetched_at": now - 300, "repos": [{}]}}, True, now))
        self.assertIn("STALE", f({"gh": {"ok": True, "fetched_at": now - 90000, "repos": []}}, True, now))


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

    def test_dirty_outranks_newer_clean(self):  # AC-20
        es = [entry("clean-new", ts=100), entry("dirty-old", ts=1, dirty=2)]
        self.assertEqual(hub.order_entries(es, self.cfg)[0]["name"], "dirty-old")

    def test_ahead_and_pr_count_as_attention(self):
        es = [entry("a", ts=9), entry("b", ts=1, ahead=1), entry("c", slug="o/c", ts=2)]
        order = hub.order_entries(es, self.cfg, {"o/c": {"pr_count": 1}})
        self.assertEqual([e["name"] for e in order], ["c", "b", "a"])

    def test_pinned_first_in_config_order(self):  # AC-18
        cfg = dict(self.cfg, pinned=["b", "a"])
        es = [entry("a", ts=5), entry("x", ts=99, dirty=3), entry("b", ts=1)]
        self.assertEqual([e["name"] for e in hub.order_entries(es, cfg)], ["b", "a", "x"])

    def test_markers(self):
        cfg = dict(self.cfg, pinned=["a"])
        m = hub.markers(entry("a", dirty=3, ahead=2, slug="o/a"), cfg, {"o/a": {"pr_count": 1}})
        self.assertEqual(m, "★ ●3 ↑2 PR1")
        self.assertEqual(hub.markers(entry("g", local=False), self.cfg), "☁")


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
        self.assertEqual({e["origin"] for e in es}, {"other", "jdk-official"})

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
        self.assertEqual(es[0]["origin"], "files")


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
    """Run bin/hub as a subprocess with a sandboxed HOME, config and PATH."""

    def env(self, path=None):
        e = dict(os.environ)
        e.update(HOME=self.tmp, HUB_CACHE_DIR=self.cache,
                 HUB_CONFIG=os.path.join(self.tmp, "config"),
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
        st = hub.aggregate({r: ("repo", commits)}, None)
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


if __name__ == "__main__":
    unittest.main()
