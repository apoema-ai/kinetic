from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from kinetic.detect_repos import propose


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def make_repo(path, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.name", "t")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "a.txt").write_text("base\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-m", "base")


def commit_file(path, name, text, msg):
    (path / name).write_text(text)
    _git(path, "add", name)
    _git(path, "commit", "-m", msg)


class ProposeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)

    def test_propose_maven(self):
        (self.d / "pom.xml").write_text("<project/>")
        self.assertEqual(propose(self.d), {"verify": "mvn -q verify", "marker": "pom.xml"})

    def test_propose_none(self):
        self.assertEqual(propose(self.d), {"verify": None, "marker": None})

    def test_makefile_needs_test_target(self):
        (self.d / "Makefile").write_text("build:\n\techo\n")
        self.assertIsNone(propose(self.d)["verify"])
        (self.d / "Makefile").write_text("build:\n\techo\ntest:\n\techo\n")
        self.assertEqual(propose(self.d), {"verify": "make test", "marker": "Makefile"})

    def test_pyproject_proposes_python3(self):
        (self.d / "pyproject.toml").write_text("[project]\n")
        self.assertEqual(propose(self.d)["verify"], "python3 -m pytest")

    def test_propose_reads_markers_from_bare_clone(self):
        src = self.d / "src"
        make_repo(src)
        commit_file(src, "pom.xml", "<project/>", "pom")
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(self.d / "b")], check=True)
        self.assertEqual(propose(self.d / "b"), {"verify": "mvn -q verify", "marker": "pom.xml"})

    def test_propose_reads_makefile_test_target_from_bare_clone(self):
        src = self.d / "src"
        make_repo(src)
        commit_file(src, "Makefile", "build:\n\techo\ntest:\n\techo\n", "mk")
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(self.d / "b")], check=True)
        self.assertEqual(propose(self.d / "b"), {"verify": "make test", "marker": "Makefile"})

    def test_propose_bare_clone_prefers_origin_ref_over_head(self):
        src = self.d / "src"
        make_repo(src)
        commit_file(src, "pom.xml", "<project/>", "pom")
        b = self.d / "b"
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(b)], check=True)
        _git(b, "update-ref", "refs/remotes/origin/main", "HEAD")
        _git(b, "update-ref", "refs/heads/main", "HEAD~1")
        self.assertEqual(propose(b)["marker"], "pom.xml")

    def test_first_match_wins(self):
        (self.d / "package.json").write_text("{}")
        (self.d / "pom.xml").write_text("<project/>")
        self.assertEqual(propose(self.d)["marker"], "pom.xml")


if __name__ == "__main__":
    unittest.main()
