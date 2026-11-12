from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kinetic import red, state


class RedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.run_dir = self.tmp / "run"
        state.init(self.run_dir, "quick", "X-1")
        self.repo = self.tmp / "svc"
        self.repo.mkdir()

    def test_failing_command_is_recorded_as_red(self):
        res = red.run(self.run_dir, "T-1", self.repo, "echo boom; exit 4")
        self.assertEqual((res["recorded"], res["exit_code"]), (True, 4))
        rec = state.load(self.run_dir)["red"]["T-1"]
        self.assertEqual((rec["exit_code"], rec["command"]), (4, "echo boom; exit 4"))
        self.assertEqual(rec["log_path"], res["log_path"])
        log = Path(res["log_path"])
        self.assertEqual(log.parent, self.run_dir / "logs")
        self.assertTrue(log.name.startswith("T-1-red-"))
        self.assertIn("boom", log.read_text())

    def test_passing_command_is_not_a_red(self):
        res = red.run(self.run_dir, "T-1", self.repo, "true")
        self.assertEqual((res["recorded"], res["exit_code"]), (False, 0))
        self.assertNotIn("T-1", state.load(self.run_dir)["red"])

    def test_passing_rerun_does_not_erase_an_earlier_red(self):
        red.run(self.run_dir, "T-1", self.repo, "false")
        red.run(self.run_dir, "T-1", self.repo, "true")
        self.assertEqual(state.load(self.run_dir)["red"]["T-1"]["exit_code"], 1)

    def test_stdin_is_closed(self):
        res = red.run(self.run_dir, "T-1", self.repo, "cat; false")  # would hang if inherited
        self.assertTrue(res["recorded"])

    def test_missing_repo_path_leaves_no_log(self):
        with self.assertRaises(OSError):
            red.run(self.run_dir, "T-1", self.tmp / "gone", "false")
        self.assertFalse((self.run_dir / "logs").exists())

    def _main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = red.main(["--run", str(self.run_dir), "--ticket", "T-1", *args])
        return code, out.getvalue(), err.getvalue()

    def test_main_exits_0_when_the_test_fails_as_red_should(self):
        code, out, _ = self._main("--repo-path", str(self.repo), "--command", "exit 3")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["recorded"], True)

    def test_main_exits_1_when_the_test_passes(self):
        code, out, err = self._main("--repo-path", str(self.repo), "--command", "true")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["recorded"], False)
        self.assertIn("not a RED", err)

    def test_main_missing_repo_path_exits_2(self):
        code, out, err = self._main("--repo-path", str(self.tmp / "gone"), "--command", "false")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not a directory", err)


if __name__ == "__main__":
    unittest.main()
