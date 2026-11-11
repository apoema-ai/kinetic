from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kinetic import doctor

SKILLS = ["find-ticket-repos", "checkout-ticket-repos", "resolving-merge-conflicts"]
PLUGINS = ["superpowers", "dev-fleet"]


class DoctorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.central = self.tmp / "repos.json"
        self.settings = self.tmp / "settings.json"
        self.repo = self.tmp / "svc"
        self.repo.mkdir()
        (self.repo / ".kinetic.json").write_text(json.dumps({"verify": "true"}))
        self._stub("git", 0)
        self._stub("gh", 0)
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.bin)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stub(self, name, code, body=""):
        p = self.bin / name
        p.write_text(f"#!/bin/sh\n{body}\nexit {code}\n")
        p.chmod(0o755)

    def _install_all_skills(self):
        for s in SKILLS:
            d = self.home / ".claude/skills" / s
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("x")
        for p in PLUGINS:
            (self.home / ".claude/plugins/cache/mkt" / p).mkdir(parents=True)

    def _by_name(self, repos=None):
        res = doctor.checks(repos if repos is not None else [("svc", str(self.repo))],
                            self.home, self.central, settings=self.settings)
        return {c["name"]: c for c in res}

    def _write_settings(self, **cfg):
        self.settings.write_text(json.dumps(cfg))

    def test_missing_gh_fails(self):
        (self.bin / "gh").unlink()
        c = self._by_name()
        self.assertEqual(c["gh"]["status"], "fail")
        self.assertTrue(c["gh"]["fix"])
        self.assertNotIn("gh-auth", c)
        self.assertEqual(c["git"]["status"], "pass")

    def test_gh_auth_failure_fails(self):
        self._stub("gh", 1)
        c = self._by_name()
        self.assertEqual(c["gh"]["status"], "pass")
        self.assertEqual(c["gh-auth"]["status"], "fail")

    def test_gh_auth_scoped_to_github_com(self):
        self._stub("gh", 1, 'case "$*" in "auth status --hostname github.com") exit 0;; esac')
        self.assertEqual(self._by_name()["gh-auth"]["status"], "pass")

    def test_gh_auth_timeout_has_own_fix(self):
        self._stub("gh", 0, "while :; do :; done")
        with mock.patch.object(doctor, "GH_TIMEOUT", 0.2):
            c = self._by_name()
        self.assertEqual(c["gh-auth"]["status"], "fail")
        self.assertIn("timed out", c["gh-auth"]["fix"])

    def test_missing_skill_warns(self):
        self._install_all_skills()
        c = self._by_name()
        for n in SKILLS + PLUGINS:
            self.assertEqual(c["skill:" + n]["status"], "pass", n)
        (self.home / ".claude/skills/find-ticket-repos/SKILL.md").unlink()
        (self.home / ".claude/plugins/cache/mkt/dev-fleet").rmdir()
        c = self._by_name()
        self.assertEqual(c["skill:find-ticket-repos"]["status"], "warn")
        self.assertEqual(c["skill:dev-fleet"]["status"], "warn")
        self.assertEqual(c["skill:superpowers"]["status"], "pass")

    def test_repo_without_verify_fails(self):
        (self.repo / ".kinetic.json").unlink()
        c = self._by_name()
        self.assertEqual(c["verify:svc"]["status"], "fail")
        self.assertIn("verify", c["verify:svc"]["fix"])

    def test_repo_with_verify_passes(self):
        c = self._by_name()
        self.assertEqual(c["verify:svc"]["status"], "pass")
        self.assertEqual(c["verify:svc"]["fix"], "")

    def test_central_config_states(self):
        self.assertEqual(self._by_name()["central-config"]["status"], "warn")
        self.central.write_text("{not json")
        self.assertEqual(self._by_name()["central-config"]["status"], "fail")
        self.central.write_text("[]")
        self.assertEqual(self._by_name()["central-config"]["status"], "fail")
        self.central.write_text("{}")
        self.assertEqual(self._by_name()["central-config"]["status"], "pass")

    def test_non_dict_repo_entry_fails_cleanly(self):
        (self.repo / ".kinetic.json").unlink()
        self.central.write_text('{"svc": "x"}')
        c = self._by_name()
        self.assertEqual(c["verify:svc"]["status"], "fail")
        out = io.StringIO()
        with mock.patch.object(doctor.config, "DEFAULT_CENTRAL", self.central), \
                mock.patch.object(doctor.Path, "home", return_value=self.home), \
                contextlib.redirect_stdout(out):
            code = doctor.main(["--repo", f"svc={self.repo}"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_bad_central_fails_repo_checks(self):
        self.central.write_text("{bad")
        c = self._by_name()
        self.assertEqual(c["central-config"]["status"], "fail")
        self.assertEqual(c["verify:svc"]["fix"], "fix central-config first")

    def test_repo_path_missing(self):
        c = self._by_name([("svc", str(self.tmp / "nope"))])
        self.assertEqual(c["verify:svc"]["status"], "fail")
        self.assertEqual(c["verify:svc"]["fix"], f"repo path not found: {self.tmp / 'nope'}")

    def test_cli_success_path(self):
        self.central.write_text("{}")
        out = io.StringIO()
        with mock.patch.object(doctor.config, "DEFAULT_CENTRAL", self.central), \
                mock.patch.object(doctor.Path, "home", return_value=self.home), \
                contextlib.redirect_stdout(out):
            code = doctor.main(["--repo", f"svc={self.repo}"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])

    def test_atlassian_warns_only_for_jira(self):
        self._write_settings(tracker="jira", jira_project="P", slice_issue_type="S",
                             child_issue_type="C")
        c = self._by_name()
        self.assertEqual(c["atlassian-mcp"]["status"], "warn")
        self.assertEqual(c["atlassian-mcp"]["fix"], "check with /mcp")
        self.assertEqual(c["tracker-access"]["status"], "warn")
        self.assertEqual(c["tracker-access"]["fix"], "check the MCP with /mcp")
        self._write_settings(tracker="local")
        self.assertNotIn("atlassian-mcp", self._by_name())

    def test_doctor_tracker_fail_on_unknown(self):
        self._write_settings(tracker="nope")
        c = self._by_name()
        self.assertEqual(c["tracker"]["status"], "fail")
        self.assertIn("unknown tracker", c["tracker"]["fix"])
        self.assertEqual(c["tracker-access"]["status"], "fail")
        self.assertEqual(c["tracker-access"]["fix"], "fix tracker settings first")

    def test_tracker_default_local_passes(self):
        c = self._by_name()
        self.assertEqual(c["tracker"]["status"], "pass")
        self.assertEqual(c["tracker-access"]["status"], "pass")
        self.assertEqual(c["pr-template"]["status"], "pass")

    def test_tracker_access_github_reuses_gh_auth(self):
        self._write_settings(tracker="github", tracker_settings={"github_repo": "o/r"})
        self.assertEqual(self._by_name()["tracker-access"]["status"], "pass")
        self._stub("gh", 1)
        c = self._by_name()
        self.assertEqual(c["tracker-access"]["status"], "fail")
        self.assertEqual(c["tracker-access"]["fix"], c["gh-auth"]["fix"])
        (self.bin / "gh").unlink()
        c = self._by_name()
        self.assertEqual(c["tracker-access"]["status"], "fail")
        self.assertEqual(c["tracker-access"]["fix"], "run: gh auth login")

    def test_doctor_pr_template_missing(self):
        self._write_settings(pr_template="nope.md")
        c = self._by_name()
        self.assertEqual(c["pr-template"]["status"], "fail")
        self.assertIn(str(self.tmp / "nope.md"), c["pr-template"]["fix"])

    def test_cli_exit_code_and_output(self):
        (self.repo / ".kinetic.json").unlink()
        out = io.StringIO()
        with mock.patch.object(doctor.config, "DEFAULT_CENTRAL", self.central), \
                mock.patch.object(doctor.Path, "home", return_value=self.home), \
                contextlib.redirect_stdout(out):
            code = doctor.main(["--repo", f"svc={self.repo}"])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertIn("verify:svc", [c["name"] for c in data["checks"]])


if __name__ == "__main__":
    unittest.main()
