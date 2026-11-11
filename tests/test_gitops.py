from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from kinetic import gitops, state


def git(path, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(path), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def make_repo(path, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", branch)
    git(path, "config", "user.name", "t")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "commit.gpgsign", "false")
    (path / "a.txt").write_text("base\n")
    git(path, "add", "a.txt")
    git(path, "commit", "-m", "base")


def commit_file(path, name, text, msg):
    (path / name).write_text(text)
    git(path, "add", name)
    git(path, "commit", "-m", msg)


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "r"
        make_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_merge_clean(self):
        git(self.repo, "checkout", "-b", "t1")
        commit_file(self.repo, "b.txt", "b\n", "add b")
        res = gitops.merge_ticket(self.repo, "t1", "main")
        self.assertEqual(res, {"merged": True, "conflicts": []})
        self.assertTrue((self.repo / "b.txt").exists())
        self.assertEqual(len(git(self.repo, "rev-list", "--parents", "-n", "1", "HEAD").split()), 3)

    def test_merge_missing_branch_raises(self):
        with self.assertRaises(RuntimeError):
            gitops.merge_ticket(self.repo, "nope", "main")

    def test_merge_conflict_filename_with_space(self):
        commit_file(self.repo, "my file.txt", "base\n", "add")
        git(self.repo, "checkout", "-b", "t1")
        commit_file(self.repo, "my file.txt", "ticket\n", "t1")
        git(self.repo, "checkout", "main")
        commit_file(self.repo, "my file.txt", "main\n", "main")
        res = gitops.merge_ticket(self.repo, "t1", "main")
        self.assertEqual(res["conflicts"], ["my file.txt"])

    def test_merge_conflict_lists_files(self):
        git(self.repo, "checkout", "-b", "t1")
        commit_file(self.repo, "a.txt", "ticket\n", "t1 edit")
        git(self.repo, "checkout", "main")
        commit_file(self.repo, "a.txt", "main\n", "main edit")
        res = gitops.merge_ticket(self.repo, "t1", "main")
        self.assertEqual(res, {"merged": False, "conflicts": ["a.txt"]})
        self.assertTrue((self.repo / ".git" / "MERGE_HEAD").exists())

    def test_create_worktree_new_and_existing_branch(self):
        dest = Path(self.tmp.name) / "wt"
        gitops.create_worktree(self.repo, dest, "feat", "main")
        self.assertTrue((dest / "a.txt").exists())
        dest2 = Path(self.tmp.name) / "wt2"
        git(self.repo, "branch", "pre")
        gitops.create_worktree(self.repo, dest2, "pre", "main")
        self.assertTrue((dest2 / "a.txt").exists())
        with self.assertRaises(RuntimeError):
            gitops.create_worktree(self.repo, Path(self.tmp.name) / "wt3", "x", "nope")


class MergeOrderTests(unittest.TestCase):
    def test_merge_order_respects_edges(self):
        tickets = {
            "T1": {"repo": "web", "blocked_by": [{"id": "T2", "type": "merge"}]},
            "T2": {"repo": "lib", "blocked_by": []},
            "T3": {"repo": "app", "blocked_by": [{"id": "T2", "type": "snapshot"}]},
            "T4": {"repo": "web", "blocked_by": [{"id": "T1", "type": "release"}]},
        }
        self.assertEqual(gitops.merge_order({"tickets": tickets}), ["app", "lib", "web"])

    def test_merge_order_skips_repoless_tickets(self):
        tickets = {"A": {"repo": None, "blocked_by": []},
                   "B": {"repo": "x", "blocked_by": [{"id": "A", "type": "merge"}]}}
        self.assertEqual(gitops.merge_order({"tickets": tickets}), ["x"])

    def test_merge_order_cycle(self):
        tickets = {
            "A": {"repo": "x", "blocked_by": [{"id": "B", "type": "merge"}]},
            "B": {"repo": "y", "blocked_by": [{"id": "A", "type": "merge"}]},
        }
        with self.assertRaises(ValueError):
            gitops.merge_order({"tickets": tickets})


class PinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.run_dir = root / "run"
        state.init(self.run_dir, "feature", "X-1")
        self.up, self.down = root / "up", root / "down"
        make_repo(self.up)
        make_repo(self.down)
        state.set_repo(self.run_dir, "up", str(self.up), "main")
        state.set_repo(self.run_dir, "down", str(self.down), "main")
        state.set_ticket(self.run_dir, "T1", repo="up", status="done")
        state.set_ticket(self.run_dir, "T3", repo="up")  # todo
        state.set_ticket(self.run_dir, "T2", repo="down")
        self.central = root / "repos.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_central(self, up, down):
        self.central.write_text(json.dumps({"up": up, "down": down}))

    def test_pin_skips_without_commands(self):
        self.write_central({"verify": "true"}, {"verify": "true", "pin": "touch ran"})
        res = gitops.pin(self.run_dir, "up", "down", central=self.central)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["log_path"])
        self.assertIn("publish_snapshot", res["reason"])
        self.assertFalse((self.down / "ran").exists())
        self.assertFalse(state.load(self.run_dir)["tickets"]["T1"]["snapshot_published"])

    def test_pin_marks_snapshot_published(self):
        self.write_central(
            {"verify": "true", "publish_snapshot": "touch published"},
            {"verify": "true", "pin": "printenv KINETIC_UPSTREAM_REF > ref.txt"})
        res = gitops.pin(self.run_dir, "up", "down", central=self.central)
        self.assertTrue(res["ok"])
        self.assertTrue(Path(res["log_path"]).is_file())
        self.assertTrue((self.up / "published").exists())
        self.assertEqual((self.down / "ref.txt").read_text().strip(), git(self.up, "rev-parse", "HEAD"))
        s = state.load(self.run_dir)
        self.assertTrue(s["tickets"]["T1"]["snapshot_published"])
        self.assertFalse(s["tickets"]["T2"]["snapshot_published"])
        self.assertFalse(s["tickets"]["T3"]["snapshot_published"])  # todo stays unmarked

    def test_pin_non_git_upstream_raises(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        state.set_repo(self.run_dir, "up", str(plain), "main")
        self.write_central({"verify": "true", "publish_snapshot": "touch published"},
                           {"verify": "true", "pin": "true"})
        with self.assertRaises(RuntimeError):
            gitops.pin(self.run_dir, "up", "down", central=self.central)
        self.assertFalse((plain / "published").exists())
        self.assertFalse(state.load(self.run_dir)["tickets"]["T1"]["snapshot_published"])

    def test_pin_unregistered_repo(self):
        with self.assertRaises(ValueError):
            gitops.pin(self.run_dir, "up", "ghost", central=self.central)

    def test_pin_failure_does_not_mark(self):
        self.write_central({"verify": "true", "publish_snapshot": "true"},
                           {"verify": "true", "pin": "exit 3"})
        res = gitops.pin(self.run_dir, "up", "down", central=self.central)
        self.assertFalse(res["ok"])
        self.assertTrue(Path(res["log_path"]).is_file())
        self.assertFalse(state.load(self.run_dir)["tickets"]["T1"]["snapshot_published"])


if __name__ == "__main__":
    unittest.main()
