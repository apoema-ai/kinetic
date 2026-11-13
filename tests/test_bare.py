from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kinetic import bare, config


def git(path, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(path), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def make_remote(path, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", branch)
    git(path, "config", "user.name", "t")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "commit.gpgsign", "false")
    (path / "a.txt").write_text("base\n")
    git(path, "add", "a.txt")
    git(path, "commit", "-m", "base")


def make_bare(remote, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--bare", str(remote), str(dest)],
                   check=True, capture_output=True, text=True)


def commit_file(path, name, text, message):
    (path / name).write_text(text)
    git(path, "add", name)
    git(path, "commit", "-m", message)


def fake_gh_then_git(remote):
    """subprocess.run stand-in: a gh argv bare-clones the local remote into its dest."""
    real = subprocess.run

    def run(argv, *args, **kwargs):
        if argv[0] == "gh":
            dest = argv[4]
            return real(["git", "clone", "--bare", str(remote), dest],
                        check=True, capture_output=True, text=True)
        return real(argv, *args, **kwargs)
    return run


class BareTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(os.path.realpath(self._td.name))
        self.settings = self.tmp / "settings.json"
        self.home = self.tmp / "home"
        self.home.mkdir()

    def test_is_bare_rejects_lookalikes(self):
        make_remote(self.tmp / "remote")
        make_bare(self.tmp / "remote", self.tmp / "b" / "api")
        fake = self.tmp / "b" / "fake"
        for d in ("objects", "refs"):
            (fake / d).mkdir(parents=True)
        (fake / "HEAD").write_text("ref: refs/heads/main\n")
        (fake / "config").write_text("[core]\n\tbare = false\n")
        self.assertTrue(bare.is_bare(self.tmp / "b" / "api"))
        self.assertFalse(bare.is_bare(fake))
        self.assertFalse(bare.is_bare(self.tmp / "remote"))
        self.assertFalse(bare.is_bare(self.tmp / "remote" / ".git"))

    def test_set_and_show_keep_other_keys(self):
        self.settings.write_text(json.dumps({"repo_roots": ["/x"], "tracker": "jira"}))
        d = self.tmp / "bares"
        d.mkdir()
        self.assertIsNone(bare.show(path=self.settings))
        self.assertEqual(bare.set_dir(str(d), path=self.settings), str(d))
        self.assertEqual(bare.show(path=self.settings), str(d))
        data = json.loads(self.settings.read_text())
        self.assertEqual((data["repo_roots"], data["tracker"]), (["/x"], "jira"))

    def test_show_rejects_non_string(self):
        self.settings.write_text(json.dumps({"bare_dir": 5}))
        with self.assertRaises(config.ConfigError):
            bare.show(path=self.settings)

    def test_set_refuses_missing_dir_unless_create(self):
        with self.assertRaises(ValueError):
            bare.set_dir(str(self.tmp / "nope"), path=self.settings)
        self.assertFalse(self.settings.exists())
        out = bare.set_dir(str(self.tmp / "nope"), create=True, path=self.settings)
        self.assertTrue(Path(out).is_dir())

    def test_set_never_overwrites_malformed_settings(self):
        self.settings.write_text("{not json")
        with self.assertRaises(config.ConfigError):
            bare.set_dir(str(self.tmp), path=self.settings)
        self.assertEqual(self.settings.read_text(), "{not json")

    def test_list_returns_bare_children_with_remote_and_default_branch(self):
        make_remote(self.tmp / "remote")
        make_bare(self.tmp / "remote", self.tmp / "b" / "api")
        (self.tmp / "b" / "notes").mkdir()
        out = bare.list_clones(str(self.tmp / "b"))
        self.assertEqual([c["name"] for c in out], ["api"])
        self.assertEqual(out[0]["remote"], str(self.tmp / "remote"))
        self.assertEqual(out[0]["default_branch"], "main")

    def test_missing_bare_dir_lists_nothing_and_clone_refuses(self):
        self.assertEqual(bare.list_clones(str(self.tmp / "gone")), [])
        with self.assertRaises(ValueError):
            bare.clone(str(self.tmp / "gone"), url=str(self.tmp / "remote"), name="api")

    def test_clone_by_url_configures_refspec_fetch_and_upstream(self):
        make_remote(self.tmp / "remote")
        (self.tmp / "b").mkdir()
        out = bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"), name="api")
        dest = self.tmp / "b" / "api"
        self.assertEqual(out, {"name": "api", "path": str(dest), "default_branch": "main"})
        self.assertTrue(bare.is_bare(dest))
        self.assertEqual(git(dest, "config", "--get", "remote.origin.fetch"),
                         "+refs/heads/*:refs/remotes/origin/*")
        self.assertEqual(git(dest, "rev-parse", "origin/main"),
                         git(self.tmp / "remote", "rev-parse", "main"))
        self.assertEqual(git(dest, "rev-parse", "--abbrev-ref", "main@{upstream}"), "origin/main")

    def test_clone_refuses_existing_target_and_bad_args(self):
        make_remote(self.tmp / "remote")
        (self.tmp / "b" / "api").mkdir(parents=True)
        with self.assertRaises(ValueError):
            bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"), name="api")
        with self.assertRaises(ValueError):
            bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"))  # no name
        with self.assertRaises(ValueError):
            bare.clone(str(self.tmp / "b"), repo="acme/api", url="x", name="api")

    def test_clone_failure_raises_runtime_error(self):
        (self.tmp / "b").mkdir()
        with self.assertRaises(RuntimeError):
            bare.clone(str(self.tmp / "b"), url=str(self.tmp / "nowhere"), name="api")

    def test_clone_by_repo_calls_gh_with_bare(self):
        make_remote(self.tmp / "remote")
        (self.tmp / "b").mkdir()
        with mock.patch.object(bare.subprocess, "run",
                               side_effect=fake_gh_then_git(self.tmp / "remote")) as run:
            out = bare.clone(str(self.tmp / "b"), repo="acme/api")
        self.assertEqual(run.call_args_list[0].args[0][:4], ["gh", "repo", "clone", "acme/api"])
        self.assertEqual(run.call_args_list[0].args[0][-2:], ["--", "--bare"])
        self.assertEqual(out["name"], "api")
        self.assertEqual(out["default_branch"], "main")

    def _two_clones(self):
        make_remote(self.tmp / "remote")
        (self.tmp / "b").mkdir()
        for n in ("api", "web"):
            bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"), name=n)

    def test_refresh_reports_advanced_refs_and_leaves_local_branch(self):
        make_remote(self.tmp / "remote")
        (self.tmp / "b").mkdir()
        bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"), name="api")
        dest = self.tmp / "b" / "api"
        old = git(dest, "rev-parse", "main")
        commit_file(self.tmp / "remote", "b.txt", "b\n", "second")
        new = git(self.tmp / "remote", "rev-parse", "main")
        [r] = bare.refresh(str(self.tmp / "b"), ["api"])
        self.assertEqual((r["ok"], r["error"]), (True, None))
        self.assertEqual(r["advanced"],
                         [{"ref": "refs/remotes/origin/main", "from": old, "to": new}])
        self.assertEqual(git(dest, "rev-parse", "main"), old)  # local branch untouched

    def test_refresh_reports_new_and_pruned_refs(self):
        make_remote(self.tmp / "remote")
        (self.tmp / "b").mkdir()
        bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"), name="api")
        git(self.tmp / "remote", "branch", "feat")
        [r] = bare.refresh(str(self.tmp / "b"), ["api"])
        sha = git(self.tmp / "remote", "rev-parse", "feat")
        self.assertEqual(r["advanced"],
                         [{"ref": "refs/remotes/origin/feat", "from": None, "to": sha}])
        git(self.tmp / "remote", "branch", "-D", "feat")
        [r] = bare.refresh(str(self.tmp / "b"), ["api"])
        self.assertEqual(r["advanced"],
                         [{"ref": "refs/remotes/origin/feat", "from": sha, "to": None}])

    def test_refresh_all_when_names_is_none(self):
        self._two_clones()
        out = bare.refresh(str(self.tmp / "b"))
        self.assertEqual([r["name"] for r in out], ["api", "web"])
        self.assertTrue(all(r["ok"] and r["advanced"] == [] for r in out))

    def test_refresh_reports_failure_and_continues(self):
        self._two_clones()
        git(self.tmp / "b" / "web", "remote", "set-url", "origin", str(self.tmp / "nowhere"))
        out = bare.refresh(str(self.tmp / "b"), ["api", "web", "nope"])
        self.assertEqual([r["ok"] for r in out], [True, False, False])
        self.assertTrue(out[1]["error"])
        self.assertIn("no bare clone named nope", out[2]["error"])

    def test_cli_refresh_exits_1_on_any_failure(self):
        self._two_clones()
        with mock.patch.object(bare, "SETTINGS", self.settings):
            self.assertEqual(bare.main(["refresh"]), 1)  # bare_dir unset
            bare.set_dir(str(self.tmp / "b"), path=self.settings)
            self.assertEqual(bare.main(["refresh"]), 0)
            self.assertEqual(bare.main(["refresh", "--name", "api", "--name", "nope"]), 1)

    def test_cli_clone_by_url_and_requires_bare_dir(self):
        make_remote(self.tmp / "remote")
        (self.tmp / "b").mkdir()
        with mock.patch.object(bare, "SETTINGS", self.settings):
            self.assertEqual(bare.main(["clone", "--url", str(self.tmp / "remote"),
                                        "--name", "api"]), 1)  # bare_dir unset
            bare.set_dir(str(self.tmp / "b"), path=self.settings)
            self.assertEqual(bare.main(["clone", "--url", str(self.tmp / "remote"),
                                        "--name", "api"]), 0)
            self.assertTrue(bare.is_bare(self.tmp / "b" / "api"))
            self.assertEqual(bare.main(["clone", "--url", str(self.tmp / "remote"),
                                        "--name", "api"]), 1)  # exists

    def test_detect_keeps_hint_when_scan_fills_the_cap(self):
        make_remote(self.tmp / "remote")
        for i in range(6):
            make_bare(self.tmp / "remote", self.home / "workspace" / f"c{i}" / "r")
        hinted = self.tmp / "hinted"
        hinted.mkdir()
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "bare-repos.local.md").write_text(
            f"---\nbare_repos_dir: {hinted}\n---\n")
        out = bare.detect(str(self.tmp), path=self.settings, home=self.home)
        paths = [c["path"] for c in out["candidates"]]
        self.assertIn(str(hinted), paths)
        self.assertLessEqual(len(paths), 5)
        self.assertEqual(out["recommendation"]["path"], str(self.home / "workspace" / "c0"))

    def test_detect_precedence(self):
        scanned = self.home / "workspace" / "master" / ".bare"
        make_remote(self.tmp / "remote")
        make_bare(self.tmp / "remote", scanned / "one")
        make_bare(self.tmp / "remote", scanned / "two")
        hinted = self.tmp / "hinted"
        hinted.mkdir()
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "bare-repos.local.md").write_text(
            f"---\nbare_repos_dir: {hinted}\n---\n\n# x\n")
        container = self.tmp / "other"
        make_bare(self.tmp / "remote", container / "x")
        worktree = self.tmp / "wt"
        git(container / "x", "worktree", "add", str(worktree), "main")

        out = bare.detect(str(self.tmp), path=self.settings, home=self.home)
        self.assertIsNone(out["saved"])
        self.assertEqual(out["recommendation"]["path"], str(scanned))
        self.assertIn(str(hinted), [c["path"] for c in out["candidates"]])

        out = bare.detect(str(worktree), path=self.settings, home=self.home)
        self.assertEqual(out["recommendation"]["path"], str(container))

        bare.set_dir(str(hinted), path=self.settings)
        out = bare.detect(str(worktree), path=self.settings, home=self.home)
        self.assertEqual(out["saved"], str(hinted))
        self.assertEqual(out["recommendation"], {"path": str(hinted), "reason": "already saved"})

    def test_detect_falls_back_to_local_md_hint(self):
        hinted = self.tmp / "hinted"
        hinted.mkdir()
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "bare-repos.local.md").write_text(
            f"---\nbare_repos_dir: {hinted}\n---\n")
        out = bare.detect(str(self.tmp), path=self.settings, home=self.home)
        self.assertEqual(out["recommendation"]["path"], str(hinted))
        self.assertEqual(out["candidates"][0]["source"], "~/.claude/bare-repos.local.md")

    def test_detect_nothing_found(self):
        out = bare.detect(str(self.tmp), path=self.settings, home=self.home)
        self.assertEqual((out["candidates"], out["recommendation"]), ([], None))

    def test_cli_show_exits_1_when_unset(self):
        with mock.patch.object(bare, "SETTINGS", self.settings):
            self.assertEqual(bare.main(["show"]), 1)

    def test_cli_set_show_list(self):
        d = self.tmp / "bares"
        d.mkdir()
        with mock.patch.object(bare, "SETTINGS", self.settings):
            self.assertEqual(bare.main(["set", "--dir", str(d)]), 0)
            self.assertEqual(bare.main(["show"]), 0)
            self.assertEqual(bare.main(["list"]), 0)

    def test_cli_list_exits_1_when_unset(self):
        with mock.patch.object(bare, "SETTINGS", self.settings):
            self.assertEqual(bare.main(["list"]), 1)


if __name__ == "__main__":
    unittest.main()
