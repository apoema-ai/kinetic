from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kinetic import state, status

ROOT = Path(__file__).resolve().parent.parent


def t(repo, st="todo", blocked_by=()):
    return {"repo": repo, "status": st, "blocked_by": list(blocked_by),
            "snapshot_published": False}


def S(tickets, gates=None, phase="build"):
    return {"lane": "feature", "phase": phase, "tickets": tickets, "gates": gates or {}}


class StatusTest(unittest.TestCase):
    def test_render_contains_ticket_rows(self):
        out = status.render(S({
            "A-1": t("api", "done"),
            "B-2": t("web", "todo", [{"id": "A-1", "type": "merge"}, {"id": "C", "type": "snapshot"}]),
            "C": t("lib", "running"),
        }))
        self.assertIn("feature", out.splitlines()[0])
        self.assertIn("build", out.splitlines()[0])
        self.assertIn("| id | kind | repo | status | blocked by |", out)
        self.assertLess(out.index("Waiting on you:"), out.index("| id | kind"))
        self.assertIn("| A-1 | agent | api | done | — |", out)
        self.assertIn("| B-2 | agent | web | todo | A-1 (merge), C (snapshot) |", out)

    def test_render_ready_line(self):
        out = status.render(S({"A": t("api")}))
        self.assertIn("Ready: A", out)
        self.assertIn("Ready: none", status.render(S({"A": t("api", "done")})))

    def test_render_shows_waiting_on_you(self):
        h = {"repo": None, "status": "todo", "blocked_by": [], "snapshot_published": False,
             "kind": "human"}
        out = status.render(S({"H": h}))
        self.assertIn("Waiting on you: H", out)
        self.assertIn("| H | human | — | todo | — |", out)
        self.assertIn("Waiting on you: none", status.render(S({"A": t("api")})))

    def test_render_gates(self):
        out = status.render(S({}, {"spec": {"approved": True}, "ship": {"approved": False}}))
        self.assertIn("spec: yes", out)
        self.assertIn("ship: no", out)

    def test_cli_prints_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            state.init(d, "quick", "X-1")
            state.set_ticket(d, "X-1", repo="api")
            r = subprocess.run([sys.executable, "-m", "kinetic.status", "--run", d],
                               capture_output=True, text=True,
                               env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("| X-1 | agent | api | todo | — |", r.stdout)


if __name__ == "__main__":
    unittest.main()
