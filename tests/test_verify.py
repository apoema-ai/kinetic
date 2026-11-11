from __future__ import annotations

import contextlib
import io
import json
from unittest import mock
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

    def test_at_is_start_time_and_repo_stored(self):
        from datetime import datetime, timezone
        self._verify_cmd("sleep 0.05")
        res = verify.run(self.run_dir, "T-1", "svc", self.repo, self.central)
        after = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        rec = state.load(self.run_dir)["verify"]["T-1"]
        self.assertLess(rec["at"], after)
        self.assertEqual(rec["repo"], "svc")
        self.assertEqual(res["exit_code"], 0)

    def test_stdin_is_closed(self):
        self._verify_cmd("cat")  # would hang if stdin were inherited
        self.assertEqual(verify.run(self.run_dir, None, "svc", self.repo, self.central)["exit_code"], 0)

    def test_missing_repo_path_leaves_no_log(self):
        gone = self.tmp / "gone"
        (self.central).write_text(json.dumps({"svc": {"verify": "true"}}))
        with self.assertRaises(OSError):
            verify.run(self.run_dir, None, "svc", gone, self.central)
        self.assertFalse((self.run_dir / "logs").exists())

    def _main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("kinetic.config.DEFAULT_CENTRAL", self.central), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = verify.main(["--run", str(self.run_dir), "--repo-name", "svc",
                                "--repo-path", str(args[0])] + list(args[1:]))
        return code, out.getvalue(), err.getvalue()

    def test_main_passes_exit_code_and_prints_json(self):
        self._verify_cmd("exit 3")
        code, out, _ = self._main(self.repo, "--ticket", "T-1")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["exit_code"], 3)

    def test_main_config_error_exits_2(self):
        code, out, err = self._main(self.repo)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no verify command for repo 'svc'", err)

    def test_main_missing_repo_path_exits_2(self):
        self.central.write_text(json.dumps({"svc": {"verify": "true"}}))
        code, out, err = self._main(self.tmp / "gone")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not a directory", err)


if __name__ == "__main__":
    unittest.main()
