from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kinetic import frontier, gitops, graph, next_step, state
from tests.fixtures import two_repo


class EpicFlowTests(unittest.TestCase):
    def test_epic_flow_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = two_repo.build(Path(tmp) / "repos")
            run = Path(tmp) / "run"
            state.init(run, "epic", "E-1")
            for name in ("lib", "svc"):
                state.set_repo(run, name, str(fx[name]), "main")
            state.set_ticket(run, "L1", repo="lib")
            state.set_ticket(run, "S1", repo="svc",
                             blocked_by=[{"id": "L1", "type": "snapshot"}])
            load = lambda: state.load(run)
            self.assertEqual(graph.validate(load()["tickets"], "epic"), [])
            self.assertEqual(frontier.ready(load()), ["L1"])

            # R15: L1 must be done before pin can mark its snapshot published
            state.set_ticket(run, "L1", status="done")
            self.assertEqual(frontier.ready(load()), [])
            res = gitops.pin(run, "lib", "svc", central=fx["central"])
            self.assertTrue(res["ok"], res)
            self.assertEqual(frontier.ready(load()), ["S1"])

            state.set_ticket(run, "S1", status="done")
            self.assertEqual(gitops.merge_order(load()), ["lib", "svc"])
            state.set_phase(run, "build")
            self.assertEqual(next_step.suggest(load())["reason"], "review and ship")


if __name__ == "__main__":
    unittest.main()
