from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kinetic import config, discover


def _git_init(path: Path, remote: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(os.path.realpath(t.name))
        self.root = self.tmp / "code"
        _git_init(self.root / "api", "git@github.com:acme/api.git")
        _git_init(self.root / "web")
        (self.root / "notes").mkdir()
        _git_init(self.root / "group" / "deep")
        (self.tmp / "api-link").symlink_to(self.root / "api")
        self.repos_json = self.tmp / "repos.json"
        self.repos_json.write_text(json.dumps(
            {"backend": {"path": str(self.tmp / "api-link"), "verify": "make test"}}))

    # settings / remember

    def test_settings_missing_file_gives_empty_lists(self):
        self.assertEqual(discover.settings(path=self.tmp / "nope.json"),
                         {"repo_roots": [], "github_orgs": []})

    def test_remember_creates_file_and_keeps_other_keys(self):
        s = self.tmp / "cfg" / "settings.json"
        out = discover.remember([str(self.root)], ["acme"], path=s)
        self.assertEqual(out, {"repo_roots": [str(self.root)], "github_orgs": ["acme"]})
        s.write_text(json.dumps(dict(json.loads(s.read_text()), tracker="jira")))
        discover.remember([], ["other"], path=s)
        data = json.loads(s.read_text())
        self.assertEqual(data["tracker"], "jira")
        self.assertEqual(data["github_orgs"], ["acme", "other"])

    def test_remember_normalizes_and_dedupes(self):
        link = self.tmp / "code-link"
        link.symlink_to(self.root)
        s = self.tmp / "settings.json"
        discover.remember([str(self.root) + "/", str(link)], ["acme"], path=s)
        out = discover.remember([str(self.root)], ["acme"], path=s)
        self.assertEqual(out["repo_roots"], [str(self.root)])
        self.assertEqual(out["github_orgs"], ["acme"])

    def test_remember_expands_home(self):
        s = self.tmp / "settings.json"
        old = os.environ.get("HOME")
        os.environ["HOME"] = str(self.tmp)
        self.addCleanup(lambda: os.environ.__setitem__("HOME", old) if old else os.environ.pop("HOME"))
        out = discover.remember(["~/code"], [], path=s)
        self.assertEqual(out["repo_roots"], [str(self.root)])

    def test_remember_rejects_non_directory_root(self):
        with self.assertRaises(ValueError):
            discover.remember([str(self.tmp / "missing")], [], path=self.tmp / "s.json")
        self.assertFalse((self.tmp / "s.json").exists())

    # scan

    def test_scan_folder_of_repos_one_level_only(self):
        names = sorted(r["name"] for r in discover.scan([str(self.root)], central=self.repos_json))
        self.assertEqual(names, ["api", "web"])

    def test_scan_root_inside_a_repo_returns_its_top_level(self):
        (self.root / "api" / "src").mkdir()
        out = discover.scan([str(self.root / "api" / "src")], central=self.repos_json)
        self.assertEqual([(r["name"], r["path"]) for r in out], [("api", str(self.root / "api"))])

    def test_scan_reports_remote(self):
        out = {r["name"]: r for r in discover.scan([str(self.root)], central=self.repos_json)}
        self.assertEqual(out["api"]["remote"], "git@github.com:acme/api.git")
        self.assertIsNone(out["web"]["remote"])

    def test_scan_marks_registered_by_real_path(self):
        out = {r["name"]: r for r in discover.scan([str(self.root)], central=self.repos_json)}
        self.assertEqual((out["api"]["registered"], out["api"]["registered_as"]), (True, "backend"))
        self.assertEqual((out["web"]["registered"], out["web"]["registered_as"]), (False, None))

    @unittest.skipIf(os.geteuid() == 0, "root can read any directory")
    def test_scan_skips_missing_root_and_unreadable_child(self):
        locked = self.root / "locked"
        _git_init(locked)
        locked.chmod(0o000)
        self.addCleanup(locked.chmod, 0o755)
        out = discover.scan([str(self.tmp / "missing"), str(self.root)], central=self.repos_json)
        self.assertEqual(sorted(r["name"] for r in out), ["api", "web"])

    # register

    def test_register_adds_entry_and_keeps_others(self):
        entry = discover.register("web", str(self.root / "web"), "npm test", pin="./pin.sh",
                                  central=self.repos_json)
        self.assertEqual(entry, {"path": str(self.root / "web"), "verify": "npm test", "pin": "./pin.sh"})
        data = json.loads(self.repos_json.read_text())
        self.assertEqual(sorted(data), ["backend", "web"])

    def test_register_refuses_empty_verify(self):
        with self.assertRaises(ValueError):
            discover.register("web", str(self.root / "web"), "  ", central=self.repos_json)
        self.assertNotIn("web", json.loads(self.repos_json.read_text()))

    def test_register_refuses_name_taken_by_other_path(self):
        with self.assertRaises(ValueError):
            discover.register("backend", str(self.root / "web"), "npm test", central=self.repos_json)

    def test_register_same_name_and_path_is_noop(self):
        before = self.repos_json.read_text()
        entry = discover.register("backend", str(self.root / "api"), "other", central=self.repos_json)
        self.assertEqual(entry["verify"], "make test")
        self.assertEqual(self.repos_json.read_text(), before)

    def test_malformed_config_is_never_overwritten(self):
        cases = (
            (self.tmp / "s.json", lambda p: discover.remember([str(self.root)], [], path=p)),
            (self.tmp / "r.json",
             lambda p: discover.register("web", str(self.root / "web"), "npm test", central=p)),
        )
        for f, call in cases:
            f.write_text("{not json")
            with self.assertRaises(config.ConfigError):
                call(f)
            self.assertEqual(f.read_text(), "{not json")

    # CLI

    def test_cli_scan_prints_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = discover.main(["scan", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(r["name"] for r in json.loads(buf.getvalue())), ["api", "web"])

    def test_cli_register_error_exits_1(self):
        err = io.StringIO()
        with mock.patch.object(discover, "REPOS", self.repos_json), contextlib.redirect_stderr(err):
            code = discover.main(["register", "--name", "x", "--path", str(self.root), "--verify", ""])
        self.assertEqual(code, 1)
        self.assertIn("verify", err.getvalue())

    def test_cli_remember_uses_patched_settings(self):
        s = self.tmp / "settings.json"
        with mock.patch.object(discover, "SETTINGS", s), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(discover.main(["remember", "--org", "acme"]), 0)
        self.assertEqual(json.loads(s.read_text())["github_orgs"], ["acme"])


if __name__ == "__main__":
    unittest.main()
