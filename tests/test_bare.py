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

    def test_missing_bare_dir_lists_nothing(self):
        self.assertEqual(bare.list_clones(str(self.tmp / "gone")), [])

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
