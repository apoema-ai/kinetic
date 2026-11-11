from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kinetic import state, verify
from kinetic.config import ConfigError


class VerifyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.run_dir = self.tmp / "run"
        state.init(self.run_dir, "quick", "X-1")
        self.repo = self.tmp / "svc"
        self.repo.mkdir()
        self.central = self.tmp / "repos.json"

    def _verify_cmd(self, cmd):
        (self.repo / ".kinetic.json").write_text(json.dumps({"verify": cmd}))

    def test_records_exit_code(self):
        for cmd, code in (("true", 0), ("false", 1)):
            self._verify_cmd(cmd)
            res = verify.run(self.run_dir, "T-1", "svc", self.repo, self.central)
            self.assertEqual(res["exit_code"], code)
            rec = state.load(self.run_dir)["verify"]["T-1"]
            self.assertEqual(rec["exit_code"], code)
            self.assertEqual(rec["log_path"], res["log_path"])

    def test_log_captures_output_and_repo_key(self):
        self._verify_cmd("echo out; echo err 1>&2")
        res = verify.run(self.run_dir, None, "svc", self.repo, self.central)
        log = Path(res["log_path"])
        self.assertEqual(log.parent, self.run_dir / "logs")
        self.assertTrue(log.name.startswith("verify-svc-"))
        self.assertIn("out", log.read_text())
        self.assertIn("err", log.read_text())
        self.assertIn("repo:svc", state.load(self.run_dir)["verify"])

    def test_missing_verify_command_errors(self):
        with self.assertRaises(ConfigError) as cm:
            verify.run(self.run_dir, "T-1", "svc", self.repo, self.central)
        msg = str(cm.exception)
        self.assertIn("svc", msg)
        self.assertIn(str(self.central), msg)
        self.assertIn(str(self.repo / ".kinetic.json"), msg)


if __name__ == "__main__":
    unittest.main()
