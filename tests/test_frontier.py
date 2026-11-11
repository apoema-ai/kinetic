from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kinetic import frontier, state

ROOT = Path(__file__).resolve().parent.parent


def t(repo, status="todo", blocked_by=(), published=False, kind="agent", after=()):
    d = {"repo": repo, "status": status, "blocked_by": [dict(b) for b in blocked_by],
         "snapshot_published": published}
    if kind != "agent":  # agent tickets stay legacy-shaped: no kind key
        d["kind"] = kind
    if after:
        d["after"] = list(after)
    return d


def S(tickets):
    return {"tickets": tickets}


def edge(i, typ):
    return {"id": i, "type": typ}


class FrontierTest(unittest.TestCase):
    def test_no_blockers_ready(self):
        self.assertEqual(frontier.ready(S({"A": t("r1")})), ["A"])

    def test_snapshot_edge_waits_for_publish(self):
        s = S({"A": t("r1", "done"), "B": t("r2", blocked_by=[edge("A", "snapshot")])})
        self.assertEqual(frontier.ready(s), [])

    def test_snapshot_edge_ready_after_publish(self):
        s = S({"A": t("r1", "done", published=True),
               "B": t("r2", blocked_by=[edge("A", "snapshot")])})
        self.assertEqual(frontier.ready(s), ["B"])

    def test_merge_edge_needs_merged(self):
        s = S({"A": t("r1", "done", published=True),
               "B": t("r2", blocked_by=[edge("A", "merge")])})
        self.assertEqual(frontier.ready(s), [])
        s["tickets"]["A"]["status"] = "merged"
        self.assertEqual(frontier.ready(s), ["B"])

    def test_release_edge_needs_released(self):
        s = S({"A": t("r1", "merged"), "B": t("r2", blocked_by=[edge("A", "release")])})
        self.assertEqual(frontier.ready(s), [])
        s["tickets"]["A"]["status"] = "released"
        self.assertEqual(frontier.ready(s), ["B"])

    def test_one_per_repo(self):
        s = S({"A": t("r1"), "B": t("r1"), "C": t("r2")})
        self.assertEqual(frontier.ready(s), ["A", "C"])

    def test_repo_with_running_ticket_blocked(self):
        s = S({"A": t("r1", "running"), "B": t("r1"), "C": t("r2")})
        self.assertEqual(frontier.ready(s), ["C"])

    def test_needs_decision_and_blocked_occupy_repo(self):
        for st in ("needs_decision", "blocked"):
            s = S({"A": t("r1", st), "B": t("r1"), "C": t("r2")})
            self.assertEqual(frontier.ready(s), ["C"], st)

    def test_needs_decision_not_counted_in_cap(self):
        s = S({"N": t("r0", "needs_decision"), "R1": t("r1", "running"),
               "R2": t("r2", "running"), "A": t("r3"), "B": t("r4")})
        self.assertEqual(frontier.ready(s), ["A"])

    def test_cap_counts_running(self):
        s = S({"R1": t("r1", "running"), "R2": t("r2", "running"),
               "A": t("r3"), "B": t("r4")})
        self.assertEqual(frontier.ready(s), ["A"])
        s["tickets"]["R3"] = t("r5", "running")
        self.assertEqual(frontier.ready(s), [])

    def test_unknown_blocker_and_no_repo_not_ready(self):
        s = S({"A": t("r1", blocked_by=[edge("ZZ", "merge")]), "B": t(None)})
        self.assertEqual(frontier.ready(s), [])

    def test_cycle_returns_empty(self):
        s = S({"A": t("r1", blocked_by=[edge("B", "merge")]),
               "B": t("r2", blocked_by=[edge("A", "merge")])})
        self.assertEqual(frontier.ready(s), [])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            state.init(d, "epic", "X-1")
            def add(s):
                s["tickets"] = {"A": t("r1"), "B": t("r2")}
            state._mutate(d, add)
            r = subprocess.run([sys.executable, "-m", "kinetic.frontier", "--run", d, "--cap", "1"],
                               capture_output=True, text=True, cwd=str(ROOT),
                               env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout),
                             {"ready": ["A"], "waiting_on_you": [], "only_human_left": False})


class HumanFrontierTest(unittest.TestCase):
    def test_human_ticket_not_dispatched(self):
        s = S({"H": t(None, kind="human")})
        self.assertEqual(frontier.ready(s), [])
        self.assertEqual(frontier.waiting_on_you(s), ["H"])

    def test_edge_onto_human_satisfied_when_done(self):
        s = S({"H": t(None, "done", kind="human"), "B": t("r2", blocked_by=[edge("H", "merge")])})
        self.assertEqual(frontier.ready(s), ["B"])

    def test_edge_onto_human_waits_while_todo(self):
        s = S({"H": t(None, kind="human"), "B": t("r2", blocked_by=[edge("H", "merge")])})
        self.assertEqual(frontier.ready(s), [])
        self.assertTrue(frontier.only_human_left(s))

    def test_snapshot_stall_is_not_only_human_left(self):
        s = S({"A": t("r1", "done"), "B": t("r2", blocked_by=[edge("A", "snapshot")])})
        self.assertFalse(frontier.only_human_left(s))

    def test_independent_agent_work_continues(self):
        s = S({"H": t(None, kind="human"), "B": t("r2", blocked_by=[edge("H", "merge")]),
               "C": t("r3")})
        self.assertEqual(frontier.ready(s), ["C"])
        self.assertFalse(frontier.only_human_left(s))

    def test_soft_precedence_orders_ready(self):
        s = S({"A": t("r1", after=["B"]), "B": t("r2")})
        self.assertEqual(frontier.ready(s), ["B", "A"])

    def test_legacy_ticket_without_new_fields(self):
        s = S({"A": t("r1"), "B": t("r1"), "C": t("r2")})
        self.assertNotIn("kind", s["tickets"]["A"])
        self.assertEqual(frontier.ready(s), ["A", "C"])
        self.assertEqual(frontier.waiting_on_you(s), [])

    def test_waiting_on_you_needs_satisfied_blockers_and_cycle_is_empty(self):
        s = S({"A": t("r1"), "H": t(None, kind="human", blocked_by=[edge("A", "merge")])})
        self.assertEqual(frontier.waiting_on_you(s), [])
        s["tickets"]["A"]["status"] = "merged"
        self.assertEqual(frontier.waiting_on_you(s), ["H"])
        cyc = S({"X": t(None, kind="human", blocked_by=[edge("Y", "merge")]),
                 "Y": t(None, kind="human", blocked_by=[edge("X", "merge")])})
        self.assertEqual(frontier.waiting_on_you(cyc), [])

    def test_only_human_left_false_when_occupied_or_nothing_todo(self):
        s = S({"H": t(None, kind="human"), "R": t("r1", "running")})
        self.assertFalse(frontier.only_human_left(s))
        self.assertFalse(frontier.only_human_left(S({"A": t("r1", "merged")})))

    def test_cli_prints_report(self):
        with tempfile.TemporaryDirectory() as d:
            state.init(d, "epic", "X-1")
            def add(s):
                s["tickets"] = {"H": t(None, kind="human")}
            state._mutate(d, add)
            r = subprocess.run([sys.executable, "-m", "kinetic.frontier", "--run", d],
                               capture_output=True, text=True, cwd=str(ROOT),
                               env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(set(json.loads(r.stdout)), {"ready", "waiting_on_you", "only_human_left"})


if __name__ == "__main__":
    unittest.main()
