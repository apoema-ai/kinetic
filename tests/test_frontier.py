from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kinetic import frontier, state

ROOT = Path(__file__).resolve().parent.parent


def t(repo, status="todo", blocked_by=(), published=False):
    return {"repo": repo, "status": status, "blocked_by": [dict(b) for b in blocked_by],
            "snapshot_published": published}


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
                s["tickets"] = {"A": t("r1"), "B": t("r1")}
            state._mutate(d, add)
            r = subprocess.run([sys.executable, "-m", "kinetic.frontier", "--run", d],
                               capture_output=True, text=True, cwd=str(ROOT),
                               env={"PYTHONPATH": str(ROOT / "scripts"), "PATH": "/usr/bin:/bin"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), {"ready": ["A"]})


if __name__ == "__main__":
    unittest.main()
