from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kinetic import frontier, state, ticket_store


class TicketStoreContract:
    """Behavior every ticket store must keep. Subclasses provide make_run()."""

    def make_run(self) -> Path:  # pragma: no cover - overridden
        raise NotImplementedError

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.run_dir = self.make_run()

    def test_set_ticket_then_load_round_trips(self):
        fields = dict(state.ticket_defaults())
        fields.update(repo="api", status="todo", kind="agent", after=[], related=[],
                      ships_with="g1", human_note=None, worktree="/tmp/wt-a",
                      produces=["Api.call"], consumes=[])
        state.set_ticket(self.run_dir, "01-api-a", **fields)
        got = state.load(self.run_dir)["tickets"]["01-api-a"]
        for key, value in fields.items():
            self.assertEqual(got.get(key), value, key)

    def test_set_ticket_status_done_requires_verify(self):
        state.set_ticket(self.run_dir, "01-api-a", repo="api")
        with self.assertRaisesRegex(ValueError, "no verify record"):
            state.set_ticket(self.run_dir, "01-api-a", require_verify=True, status="done")

    def test_human_done(self):
        state.set_ticket(self.run_dir, "02-check", kind="human")
        state.human_done(self.run_dir, "02-check", note="looked fine")
        t = state.load(self.run_dir)["tickets"]["02-check"]
        self.assertEqual((t["status"], t["done_by"], t["human_note"]),
                         ("done", "human", "looked fine"))

    def test_frontier_ready_matches(self):
        state.set_ticket(self.run_dir, "01-r1-a", repo="r1")
        state.set_ticket(self.run_dir, "02-r2-b", repo="r2",
                         blocked_by=[{"id": "01-r1-a", "type": "merge"}])
        state.set_ticket(self.run_dir, "03-r3-c", repo="r3")
        self.assertEqual(frontier.ready(state.load(self.run_dir)), ["01-r1-a", "03-r3-c"])


class LocalContractTest(TicketStoreContract, unittest.TestCase):
    def make_run(self) -> Path:
        run_dir = self.tmp / "run"
        state.init(run_dir, "feature", "ABC-1")
        return run_dir


class LocalStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name) / "run"

    def test_init_records_local_store(self):
        st = state.init(self.run_dir, "feature", "ABC-1")
        self.assertEqual(st["ticket_store"], {"kind": "local"})
        self.assertIsInstance(ticket_store.for_state(st), ticket_store.LocalTicketStore)

    def test_state_without_ticket_store_key_loads_as_local(self):
        state.init(self.run_dir, "feature", "ABC-1")
        f = self.run_dir / "state.json"
        raw = json.loads(f.read_text())
        raw.pop("ticket_store")
        f.write_text(json.dumps(raw))
        state.set_ticket(self.run_dir, "01-api-a", repo="api")
        st = state.load(self.run_dir)
        self.assertEqual(st["tickets"]["01-api-a"]["repo"], "api")
        self.assertNotIn("ticket_store", json.loads(f.read_text()))
        self.assertIsInstance(ticket_store.for_state(st), ticket_store.LocalTicketStore)

    def test_for_tracker_without_store_module_is_local(self):
        for tracker in ("github", "jira", "linear", "local", "other"):
            self.assertEqual(ticket_store.for_tracker(tracker), {"kind": "local"}, tracker)

    def test_local_store_contract_methods(self):
        st = state.init(self.run_dir, "feature", "ABC-1")
        store = ticket_store.for_state(st)
        self.assertIsNone(store.stage_path(self.run_dir))
        state.set_ticket(self.run_dir, "01-api-a", repo="api")
        st = state.load(self.run_dir)
        self.assertEqual(store.publish(self.run_dir, st), {"01-api-a": "01-api-a"})
        self.assertIsNone(store.touch(self.run_dir, st, "01-api-a"))
        self.assertEqual(store.health(Path("settings.json")), [])


if __name__ == "__main__":
    unittest.main()


class LocalPublishTest(unittest.TestCase):
    def test_local_publish_is_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            state.init(run_dir, "feature", "ABC-1")
            state.set_slices(run_dir, ["01-core"])
            state.set_ticket(run_dir, "01-api-a", repo="api", slice="01-core")
            before = json.loads((run_dir / "state.json").read_text())["tickets"]
            state.record_gate(run_dir, "breakdown", True)
            self.assertEqual(state.publish_tickets(run_dir), {"01-api-a": "01-api-a"})
            after = json.loads((run_dir / "state.json").read_text())
            self.assertEqual(after["tickets"], before)
            self.assertEqual(after["slices"], ["01-core"])
