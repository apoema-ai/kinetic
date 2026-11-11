from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kinetic import state


class StateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name) / "run"

    def test_init_writes_schema(self):
        s = state.init(self.run_dir, "feature", "ABC-1")
        for key in ("run_id", "lane", "ref", "phase", "tickets", "gates",
                    "rulings", "verify", "last_edit_at"):
            self.assertIn(key, s)
        self.assertEqual(s["phase"], "intake")
        self.assertEqual(state.load(self.run_dir), s)

    def test_init_has_slices(self):  # R1
        self.assertEqual(state.init(self.run_dir, "epic", "E-1")["slices"], [])

    def test_init_has_repos_and_set_repo(self):  # R2
        s = state.init(self.run_dir, "epic", "E-1")
        self.assertEqual(s["repos"], {})
        state.set_repo(self.run_dir, "api", "/w/api", "kinetic/int")
        self.assertEqual(state.load(self.run_dir)["repos"]["api"],
                         {"path": "/w/api", "integration_branch": "kinetic/int"})

    def test_init_stores_run_dir(self):  # R3
        s = state.init(self.run_dir, "quick", "Q-1")
        self.assertEqual(s["run_dir"], str(self.run_dir))

    def test_save_is_atomic(self):
        s = state.init(self.run_dir, "quick", "Q-1")
        s["phase"] = "build"
        state.save(self.run_dir, s)
        self.assertEqual([p.name for p in self.run_dir.iterdir() if p.name.endswith(".tmp")], [])
        self.assertEqual(state.load(self.run_dir), s)

    def test_invalid_lane_rejected(self):
        with self.assertRaises(ValueError):
            state.init(self.run_dir, "bogus", "X-1")

    def test_set_ticket_defaults_and_updates(self):
        state.init(self.run_dir, "epic", "E-1")
        t = state.set_ticket(self.run_dir, "T1", repo="api", status="todo")["tickets"]["T1"]
        self.assertFalse(t["snapshot_published"])
        self.assertEqual(t["blocked_by"], [])
        t = state.set_ticket(self.run_dir, "T1", status="running")["tickets"]["T1"]
        self.assertEqual((t["repo"], t["status"]), ("api", "running"))
        with self.assertRaises(ValueError):
            state.set_ticket(self.run_dir, "T1", status="nope")

    def test_stale_running_reported(self):
        state.init(self.run_dir, "epic", "E-1")
        state.set_ticket(self.run_dir, "T1", status="running")
        reports = self.run_dir / "reports"
        reports.mkdir()
        self.assertEqual(state.stale_running(state.load(self.run_dir), reports), ["T1"])
        (reports / "T1.md").write_text("done")
        self.assertEqual(state.stale_running(state.load(self.run_dir), reports), [])

    def test_record_verify_after_edit(self):
        state.init(self.run_dir, "quick", "Q-1")
        state.record_edit(self.run_dir, "a.py")
        state.record_verify(self.run_dir, "T1", 0, "log.txt")
        s = state.load(self.run_dir)
        self.assertGreater(s["verify"]["T1"]["at"], s["last_edit_at"])

    def test_record_verify_repo_key(self):  # R4
        state.init(self.run_dir, "epic", "E-1")
        state.record_verify(self.run_dir, None, 1, "l.txt", repo_name="api")
        v = state.load(self.run_dir)["verify"]["repo:api"]
        self.assertEqual((v["exit_code"], v["log_path"]), (1, "l.txt"))
        with self.assertRaises(ValueError):
            state.record_verify(self.run_dir, None, 0, "l.txt")

    def test_gate_and_ruling(self):
        state.init(self.run_dir, "feature", "F-1")
        state.record_gate(self.run_dir, "ship", True, "ok")
        state.add_ruling(self.run_dir, "what", "why", "cost")
        s = state.load(self.run_dir)
        self.assertTrue(s["gates"]["ship"]["approved"])
        self.assertEqual(s["rulings"][0]["what"], "what")


if __name__ == "__main__":
    unittest.main()
