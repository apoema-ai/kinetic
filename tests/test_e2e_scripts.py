from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from kinetic import frontier, gitops, graph, next_step, state, verify
from tests.fixtures import two_repo


def commit(path, name):
    (Path(path) / name).write_text(name + "\n")
    for args in (("add", name), ("commit", "-m", name)):
        subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(path), *args],
                       check=True, capture_output=True, text=True)


class EpicFlowTests(unittest.TestCase):
    """Follows skills/run/guides/build-loop.md: integration worktrees under <run>/worktrees/<repo> on
    kinetic/<run-id>/integration, ticket worktrees on kinetic/<run-id>/<id> cut at dispatch time."""

    def test_epic_flow_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = two_repo.build(Path(tmp) / "repos")
            run = Path(tmp) / "run"
            rid = state.init(run, "epic", "E-1")["run_id"]
            integ_branch = f"kinetic/{rid}/integration"
            for name in ("lib", "svc"):
                wt = run / "worktrees" / name
                gitops.create_worktree(fx[name], wt, integ_branch, "main")
                state.set_repo(run, name, str(wt), integ_branch)
            state.set_ticket(run, "L1", repo="lib")
            state.set_ticket(run, "S1", repo="svc",
                             blocked_by=[{"id": "L1", "type": "snapshot"}])
            state.set_ticket(run, "L2", repo="lib",
                             blocked_by=[{"id": "S1", "type": "merge"}])
            load = lambda: state.load(run)
            self.assertEqual(graph.validate(load()["tickets"], "epic"), [])
            self.assertEqual(frontier.ready(load()), ["L1"])

            def build_ticket(tid):
                repo = load()["tickets"][tid]["repo"]
                wt = run / "worktrees" / f"{repo}-{tid}"
                branch = f"kinetic/{rid}/{tid}"
                gitops.create_worktree(load()["repos"][repo]["path"], wt, branch, integ_branch)
                state.set_ticket(run, tid, branch=branch, worktree=str(wt), status="running")
                commit(wt, f"{tid}.txt")
                state.record_edit(run, str(wt / f"{tid}.txt"))
                v = verify.run(run, tid, repo, str(wt), central=fx["central"])
                self.assertEqual(v["exit_code"], 0)
                state.set_ticket(run, tid, status="done")
                res = gitops.merge_ticket(load()["repos"][repo]["path"], branch, integ_branch)
                self.assertEqual(res, {"merged": True, "conflicts": []})
                state.set_ticket(run, tid, status="merged")

            build_ticket("L1")
            # R15: pin marks L1 snapshot_published; only then is S1 ready
            self.assertEqual(frontier.ready(load()), [])
            res = gitops.pin(run, "lib", "svc", central=fx["central"])
            self.assertTrue(res["ok"], res)
            self.assertEqual(frontier.ready(load()), ["S1"])
            build_ticket("S1")
            self.assertEqual(frontier.ready(load()), ["L2"])
            build_ticket("L2")

            # the merge edge L2(lib) <- S1(svc) orders svc before lib; names alone would give lib first
            self.assertEqual(gitops.merge_order(load()), ["svc", "lib"])
            state.set_phase(run, "build")
            self.assertEqual(next_step.suggest(load())["reason"], "review and ship")


if __name__ == "__main__":
    unittest.main()
