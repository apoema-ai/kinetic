from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kinetic import state


def _writer(args):
    run_dir, n = args
    for i in range(25):
        state.set_ticket(run_dir, f"P{n}-{i}", status="todo")


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

    def test_record_verify_explicit_at(self):
        state.init(self.run_dir, "quick", "Q-1")
        state.record_verify(self.run_dir, "T1", 0, "l.txt", at="2000-01-01T00:00:00+00:00")
        self.assertEqual(state.load(self.run_dir)["verify"]["T1"]["at"], "2000-01-01T00:00:00+00:00")

    def test_record_verify_stores_repo(self):  # R14
        state.init(self.run_dir, "epic", "E-1")
        state.set_ticket(self.run_dir, "T1", repo="api")
        state.set_ticket(self.run_dir, "T2")
        state.record_verify(self.run_dir, "T1", 0, "l")
        state.record_verify(self.run_dir, "T2", 0, "l")
        state.record_verify(self.run_dir, "T3", 0, "l", repo_name="web")
        state.record_verify(self.run_dir, None, 0, "l", repo_name="db")
        v = state.load(self.run_dir)["verify"]
        self.assertEqual([v["T1"]["repo"], v["T2"]["repo"], v["T3"]["repo"], v["repo:db"]["repo"]],
                         ["api", None, "web", "db"])

    def test_gate_and_ruling(self):
        state.init(self.run_dir, "feature", "F-1")
        state.record_gate(self.run_dir, "ship", True, "ok")
        state.add_ruling(self.run_dir, "what", "why", "cost")
        s = state.load(self.run_dir)
        self.assertTrue(s["gates"]["ship"]["approved"])
        self.assertEqual(s["rulings"][0]["what"], "what")

    def test_concurrent_writers_keep_all_updates(self):
        state.init(self.run_dir, "epic", "E-1")
        with multiprocessing.Pool(4) as pool:
            pool.map(_writer, [(str(self.run_dir), n) for n in range(4)])
        self.assertEqual(len(state.load(self.run_dir)["tickets"]), 100)

    def test_set_phase(self):  # R11
        state.init(self.run_dir, "quick", "Q-1")
        self.assertEqual(state.set_phase(self.run_dir, "build")["phase"], "build")
        with self.assertRaises(ValueError):
            state.set_phase(self.run_dir, "nope")

    def test_set_slices(self):  # R17
        state.init(self.run_dir, "epic", "E-1")
        self.assertEqual(state.set_slices(self.run_dir, ["S1", "S2"])["slices"], ["S1", "S2"])
        self.assertEqual(state.set_slices(self.run_dir, ["S3"])["slices"], ["S3"])
        self.assertEqual(state.load(self.run_dir)["slices"], ["S3"])

    def test_set_slices_invalid(self):  # R17
        state.init(self.run_dir, "epic", "E-1")
        for bad in ("S1", ["S1", ""], ["S1", 2], [None]):
            with self.assertRaises(ValueError):
                state.set_slices(self.run_dir, bad)
        self.assertEqual(state.load(self.run_dir)["slices"], [])

    def test_record_edit_routes_by_repo(self):  # R12
        state.init(self.run_dir, "epic", "E-1")
        repo = Path(self._tmp.name) / "repo"
        repo.mkdir()
        state.set_repo(self.run_dir, "api", str(repo), "int")
        state.record_edit(self.run_dir, str(repo / "a.py"))
        s = state.load(self.run_dir)
        self.assertIsNotNone(s["repos"]["api"]["last_edit_at"])
        self.assertIsNone(s["last_edit_at"])
        state.record_edit(self.run_dir, str(Path(self._tmp.name) / "other.py"))
        self.assertIsNotNone(state.load(self.run_dir)["last_edit_at"])

    def test_record_edit_routes_ticket_worktree_to_repo(self):  # R24
        state.init(self.run_dir, "epic", "E-1")
        wt = Path(self._tmp.name) / "run" / "worktrees" / "api-T1"
        wt.mkdir(parents=True)
        state.set_repo(self.run_dir, "api", str(Path(self._tmp.name) / "api"), "int")
        state.set_ticket(self.run_dir, "T1", repo="api", worktree=str(wt))
        state.record_edit(self.run_dir, str(wt / "a.py"))
        s = state.load(self.run_dir)
        self.assertIsNotNone(s["repos"]["api"]["last_edit_at"])
        self.assertIsNone(s["last_edit_at"])

    def test_record_edit_ticket_worktree_without_repo_falls_back(self):  # R24
        state.init(self.run_dir, "epic", "E-1")
        wt = Path(self._tmp.name) / "wt"
        wt.mkdir()
        state.set_ticket(self.run_dir, "T1", worktree=str(wt))
        state.record_edit(self.run_dir, str(wt / "a.py"))
        self.assertIsNotNone(state.load(self.run_dir)["last_edit_at"])

    def test_record_edit_ignores_run_dir_artifacts(self):  # R25
        state.init(self.run_dir, "epic", "E-1")
        (Path(self.run_dir) / "reports").mkdir()
        state.record_edit(self.run_dir, str(Path(self.run_dir) / "reports" / "T1.md"))
        state.record_edit(self.run_dir, str(Path(self.run_dir) / "spec.md"))
        self.assertIsNone(state.load(self.run_dir)["last_edit_at"])

    def test_init_refuses_existing_unless_force(self):
        state.init(self.run_dir, "quick", "Q-1")
        with self.assertRaises(FileExistsError):
            state.init(self.run_dir, "quick", "Q-2")
        self.assertEqual(state.init(self.run_dir, "quick", "Q-2", force=True)["ref"], "Q-2")

    def test_blocked_by_validated(self):
        state.init(self.run_dir, "epic", "E-1")
        with self.assertRaises(ValueError):
            state.set_ticket(self.run_dir, "T1", blocked_by=[{"id": "T0", "type": "bogus"}])
        with self.assertRaises(ValueError):
            state.set_ticket(self.run_dir, "T1", blocked_by=[{"type": "merge"}])


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = str(Path(self._tmp.name) / "run")

    def cli(self, *args):
        env = dict(os.environ, PYTHONPATH="scripts")
        return subprocess.run([sys.executable, "-m", "kinetic.state", *args, "--run", self.run_dir],
                              capture_output=True, text=True, env=env)

    def test_set_ticket_blocked_by_and_string_value(self):
        self.assertEqual(self.cli("init", "--lane", "epic", "--ref", "E").returncode, 0)
        r = self.cli("set-ticket", "--id", "T1", "--field", 'blocked_by=[{"id":"T0","type":"merge"}]',
                     "--field", "branch=123")
        self.assertEqual(r.returncode, 0, r.stderr)
        t = state.load(self.run_dir)["tickets"]["T1"]
        self.assertEqual(t["blocked_by"], [{"id": "T0", "type": "merge"}])
        self.assertEqual(t["branch"], "123")

    def _ticket_in_repo(self):
        self.cli("init", "--lane", "epic", "--ref", "E")
        self.cli("set-ticket", "--id", "T1", "--field", "repo=api")

    def test_cli_refuses_done_without_verify(self):
        self._ticket_in_repo()
        r = self.cli("set-ticket", "--id", "T1", "--field", "status=done")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no verify", r.stderr)
        self.assertEqual(state.load(self.run_dir)["tickets"]["T1"]["status"], "todo")

    def test_cli_refuses_done_on_failing_verify(self):
        self._ticket_in_repo()
        state.record_verify(self.run_dir, "T1", 1, "l")
        r = self.cli("set-ticket", "--id", "T1", "--field", "status=done_with_concerns")
        self.assertEqual(r.returncode, 1)
        self.assertIn("exit 1", r.stderr)

    def test_cli_refuses_done_when_ticket_edited_after_verify(self):
        self._ticket_in_repo()
        state.record_verify(self.run_dir, "T1", 0, "l", at="2026-01-01T00:00:00.000000+00:00")
        state._mutate(self.run_dir, lambda s: s["repos"].setdefault("api", {}).update(
            last_edit_at="2026-01-01T00:00:05.000000+00:00", last_edit_ticket="T1"))
        r = self.cli("set-ticket", "--id", "T1", "--field", "status=done")
        self.assertEqual(r.returncode, 1)
        self.assertIn("edited after", r.stderr)

    def test_cli_allows_done_after_passing_verify(self):
        self._ticket_in_repo()
        state._mutate(self.run_dir, lambda s: s["repos"].setdefault("api", {}).update(
            last_edit_at="2026-01-01T00:00:00.000000+00:00", last_edit_ticket="T1"))
        state.record_verify(self.run_dir, "T1", 0, "l", at="2026-01-01T00:00:05.000000+00:00")
        r = self.cli("set-ticket", "--id", "T1", "--field", "status=done")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(state.load(self.run_dir)["tickets"]["T1"]["status"], "done")

    def test_python_set_ticket_does_not_require_verify(self):
        self._ticket_in_repo()
        state.set_ticket(self.run_dir, "T1", status="done")
        self.assertEqual(state.load(self.run_dir)["tickets"]["T1"]["status"], "done")

    def test_set_slices_cli(self):  # R17
        self.cli("init", "--lane", "epic", "--ref", "E")
        r = self.cli("set-slices", "--slices", '["S1","S2"]')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(state.load(self.run_dir)["slices"], ["S1", "S2"])
        for bad in ('"S1"', '["S1",""]', "notjson"):
            self.assertNotEqual(self.cli("set-slices", "--slices", bad).returncode, 0)
        self.assertEqual(state.load(self.run_dir)["slices"], ["S1", "S2"])

    def test_bad_edge_type_and_missing_equals_fail(self):
        self.cli("init", "--lane", "epic", "--ref", "E")
        r = self.cli("set-ticket", "--id", "T1", "--field", 'blocked_by=[{"id":"T0","type":"x"}]')
        self.assertNotEqual(r.returncode, 0)
        r = self.cli("set-ticket", "--id", "T1", "--field", "noequals")
        self.assertNotEqual(r.returncode, 0)

    def test_snapshot_published_boolean_case_insensitive(self):
        self.cli("init", "--lane", "epic", "--ref", "E")
        for raw, want in (("False", False), ("TRUE", True), ("false", False)):
            r = self.cli("set-ticket", "--id", "T1", "--field", f"snapshot_published={raw}")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIs(state.load(self.run_dir)["tickets"]["T1"]["snapshot_published"], want)

    def test_invalid_boolean_rejected(self):
        self.cli("init", "--lane", "epic", "--ref", "E")
        r = self.cli("record-gate", "--gate", "ship", "--approved", "ture")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(state.load(self.run_dir)["gates"], {})


class HumanTicketTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = str(Path(self._tmp.name) / "run")
        state.init(self.run_dir, "epic", "E")

    def ticket(self, tid):
        return state.load(self.run_dir)["tickets"][tid]

    def test_defaults_include_new_fields(self):
        state.set_ticket(self.run_dir, "A", repo="r")
        t = self.ticket("A")
        self.assertEqual(t["kind"], "agent")
        self.assertEqual(t["after"], [])
        self.assertIsNone(t["ships_with"])
        self.assertEqual(t["related"], [])
        self.assertIsNone(t["human_note"])
        self.assertIsNone(t["done_by"])

    def test_field_falls_back_for_old_tickets(self):
        self.assertEqual(state.field({"repo": "r"}, "kind"), "agent")
        self.assertEqual(state.field({"kind": "human"}, "kind"), "human")

    def test_invalid_field_values_rejected(self):
        for bad in ({"kind": "robot"}, {"after": "A"}, {"after": [1]}, {"related": [None]},
                    {"ships_with": 3}):
            with self.assertRaises(ValueError, msg=bad):
                state.set_ticket(self.run_dir, "A", **bad)
        with self.assertRaisesRegex(ValueError, "kind"):
            state.set_ticket(self.run_dir, "A", kind="robot")

    def test_human_done_sets_fields_without_verify(self):
        state.set_ticket(self.run_dir, "H", kind="human")
        t = state.human_done(self.run_dir, "H", "tf apply ok")["tickets"]["H"]
        self.assertEqual(t["status"], "done")
        self.assertEqual(t["done_by"], "human")
        self.assertEqual(t["human_note"], "tf apply ok")
        self.assertEqual(state.load(self.run_dir)["verify"], {})

    def test_human_done_rejects_agent_ticket(self):
        state.set_ticket(self.run_dir, "A")
        with self.assertRaisesRegex(ValueError, "kind=human"):
            state.human_done(self.run_dir, "A")

    def test_human_done_rejects_missing_ticket(self):
        with self.assertRaises(ValueError):
            state.human_done(self.run_dir, "nope")

    def test_set_ticket_done_refused_for_human(self):
        state.set_ticket(self.run_dir, "H", kind="human")
        with self.assertRaisesRegex(ValueError, "human-done"):
            state.set_ticket(self.run_dir, "H", require_verify=True, status="done")
        with self.assertRaisesRegex(ValueError, "human-done"):
            state.set_ticket(self.run_dir, "H", status="done_with_concerns")

    def test_set_ticket_kind_human_and_done_together_refused(self):
        with self.assertRaises(ValueError):
            state.set_ticket(self.run_dir, "N", require_verify=True, kind="human", status="done")
        self.assertNotIn("N", state.load(self.run_dir)["tickets"])

    def test_cli_human_done(self):
        state.set_ticket(self.run_dir, "H", kind="human")
        self.assertEqual(state.main(["human-done", "--run", self.run_dir, "--id", "H", "--note", "x"]), 0)
        self.assertEqual(self.ticket("H")["human_note"], "x")

    def test_cli_ships_with_null(self):
        state.set_ticket(self.run_dir, "A", ships_with="B")
        self.assertEqual(state.main(["set-ticket", "--run", self.run_dir, "--id", "A",
                                     "--field", "ships_with=null"]), 0)
        self.assertIsNone(self.ticket("A")["ships_with"])


if __name__ == "__main__":
    unittest.main()
