from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kinetic import next_step, state

ROOT = Path(__file__).resolve().parent.parent


def t(repo="r", st="todo"):
    return {"repo": repo, "status": st, "blocked_by": [], "snapshot_published": False}


class SuggestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = self._tmp.name
        (Path(self.run_dir) / "reports").mkdir()
        self.addCleanup(self._tmp.cleanup)

    def S(self, tickets=None, phase="build", gates=None):
        return {"run_dir": self.run_dir, "phase": phase, "tickets": tickets or {},
                "gates": gates or {}}

    def test_r1_no_state(self):
        r = next_step.suggest(None)
        self.assertEqual(r["command"], "/kinetic:run <ref>")
        self.assertIn("no active run", r["reason"])

    def test_r2_needs_decision(self):
        r = next_step.suggest(self.S({"A": t("r1", "needs_decision")}))
        self.assertEqual(r["command"], "/kinetic:run")
        self.assertIn("ticket A needs a decision", r["reason"])

    def test_r3_stale_running(self):
        r = next_step.suggest(self.S({"A": t("r1", "running")}))
        self.assertEqual(r["command"], "/kinetic:run")
        self.assertIn("recover A", r["reason"])

    def test_r3_running_with_report_is_not_stale(self):
        (Path(self.run_dir) / "reports" / "A.md").write_text("x")
        r = next_step.suggest(self.S({"A": t("r1", "running")}))
        self.assertNotIn("recover", r["reason"])

    def test_r4_build_frontier(self):
        r = next_step.suggest(self.S({"A": t("r1"), "B": t("r2")}))
        self.assertEqual(r["command"], "/kinetic:run")
        self.assertIn("2 tickets ready", r["reason"])

    def test_r5_build_all_done(self):
        r = next_step.suggest(self.S({"A": t("r1", "done"), "B": t("r2", "merged")}))
        self.assertEqual(r["command"], "/kinetic:run")
        self.assertIn("review and ship", r["reason"])

    def test_r6_ship_done(self):
        r = next_step.suggest(self.S({"A": t("r1", "done")}, phase="ship",
                                     gates={"ship": {"approved": True}}))
        self.assertEqual(r["command"], "/kinetic:run")
        self.assertIn("retro", r["reason"])

    def test_r7_fallback_status(self):
        r = next_step.suggest(self.S({"A": t("r1", "done")}, phase="spec"))
        self.assertEqual(r["command"], "/kinetic:status")

    def test_rule_order_earlier_wins(self):
        # needs_decision (R2) and stale running (R3) both match
        r = next_step.suggest(self.S({"A": t("r1", "needs_decision"), "B": t("r2", "running")}))
        self.assertIn("needs a decision", r["reason"])
        # stale running (R3) and a ready ticket (R4) both match
        r = next_step.suggest(self.S({"A": t("r1", "running"), "B": t("r2")}))
        self.assertIn("recover", r["reason"])


class CliTest(unittest.TestCase):
    def _run(self, args, home):
        return subprocess.run([sys.executable, "-m", "kinetic.next_step"] + args,
                              capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(ROOT / "scripts"),
                                   "HOME": home})

    def test_cli_run_flag(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as d:
            state.init(d, "quick", "X-1")
            r = self._run(["--run", d], home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["command"], "/kinetic:status")

    def test_pointer_absent_or_empty_or_dangling(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(json.loads(self._run([], home).stdout)["command"], "/kinetic:run <ref>")
            cfg = Path(home) / ".config" / "kinetic"
            cfg.mkdir(parents=True)
            (cfg / "active-run").write_text("\n")
            self.assertEqual(json.loads(self._run([], home).stdout)["command"], "/kinetic:run <ref>")
            (cfg / "active-run").write_text(str(Path(home) / "nowhere"))
            self.assertEqual(json.loads(self._run([], home).stdout)["command"], "/kinetic:run <ref>")

    def test_pointer_to_run(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as d:
            state.init(d, "quick", "X-1")
            cfg = Path(home) / ".config" / "kinetic"
            cfg.mkdir(parents=True)
            (cfg / "active-run").write_text(d + "\n")
            self.assertEqual(json.loads(self._run([], home).stdout)["command"], "/kinetic:status")

    def test_active_run_path_uses_home(self):
        with mock.patch("os.path.expanduser", return_value="/h"):
            self.assertEqual(str(next_step.active_run_file()), "/h/.config/kinetic/active-run")


if __name__ == "__main__":
    unittest.main()
