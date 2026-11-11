from __future__ import annotations

import unittest

from kinetic import graph


def t(repo="r", slice=None, blocked_by=()):
    return {"repo": repo, "slice": slice, "status": "todo",
            "blocked_by": [{"id": i, "type": ty} for i, ty in blocked_by],
            "branch": None, "report": None}


def io(ticket, produces=(), consumes=()):
    ticket["produces"], ticket["consumes"] = list(produces), list(consumes)
    return ticket


class InterfaceTest(unittest.TestCase):
    def test_consumer_without_edge_to_producer_is_error(self):
        tickets = {"A": io(t(repo="lib"), produces=["Client.export"]),
                   "B": io(t(repo="api"), consumes=["Client.export"])}
        res = graph.interface_issues(tickets)
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("B", res["errors"][0])
        self.assertIn("Client.export", res["errors"][0])
        self.assertTrue(any("Client.export" in e for e in graph.validate(tickets, "epic")))

    def test_transitive_edge_satisfies_consumer(self):
        tickets = {"A": io(t(), produces=["X"]),
                   "B": t(blocked_by=[("A", "merge")]),
                   "C": io(t(blocked_by=[("B", "merge")]), consumes=["X"])}
        self.assertEqual(graph.interface_issues(tickets), {"errors": [], "warnings": []})

    def test_unproduced_interface_is_warning_only(self):
        res = graph.interface_issues({"A": io(t(), consumes=["Legacy.api"])})
        self.assertEqual(res["errors"], [])
        self.assertEqual(len(res["warnings"]), 1)
        self.assertIn("Legacy.api", res["warnings"][0])

    def test_self_produced_and_missing_fields_ignored(self):
        tickets = {"A": io(t(), produces=["X"], consumes=["X"]), "B": t()}
        self.assertEqual(graph.interface_issues(tickets), {"errors": [], "warnings": []})


class GraphTest(unittest.TestCase):
    def test_cycle_detected(self):
        tickets = {"A": t(blocked_by=[("B", "merge")]), "B": t(blocked_by=[("A", "merge")])}
        errors = graph.validate(tickets, "epic")
        self.assertTrue(any("cycle" in e for e in errors))

    def test_child_without_repo(self):
        errors = graph.validate({"A": t(repo=None)}, "epic")
        self.assertEqual(len(errors), 1)
        self.assertIn("A", errors[0])

    def test_invalid_edge_type(self):
        errors = graph.validate({"A": t(), "B": t(blocked_by=[("A", "soon")])}, "epic")
        self.assertEqual(len(errors), 1)
        self.assertIn("B", errors[0])
        self.assertIn("soon", errors[0])

    def test_unknown_blocker(self):
        errors = graph.validate({"A": t(blocked_by=[("Z", "merge")])}, "epic")
        self.assertEqual(len(errors), 1)
        self.assertIn("A", errors[0])
        self.assertIn("Z", errors[0])

    def test_slice_without_children(self):
        errors = graph.validate({"A": t(slice="S2")}, "epic", slices=["S1", "S2"])
        self.assertEqual(len(errors), 1)
        self.assertIn("S1", errors[0])

    def test_valid_epic_graph_empty(self):
        tickets = {"A": t(slice="S1"), "B": t(slice="S1", blocked_by=[("A", "snapshot")]),
                   "C": t(blocked_by=[("B", "release")])}
        self.assertEqual(graph.validate(tickets, "epic", slices=["S1"]), [])

    def test_topo_order_blockers_first(self):
        tickets = {"C": t(blocked_by=[("A", "merge"), ("B", "merge")]),
                   "B": t(blocked_by=[("A", "merge")]), "A": t(), "D": t()}
        self.assertEqual(graph.topo_order(tickets), ["A", "B", "C", "D"])

    def test_topo_order_cycle_raises(self):
        tickets = {"A": t(blocked_by=[("B", "merge")]), "B": t(blocked_by=[("A", "merge")])}
        with self.assertRaises(ValueError):
            graph.topo_order(tickets)


class SoftLinksTest(unittest.TestCase):
    def test_after_breaks_ties(self):
        tickets = {"A": t(), "B": t()}
        tickets["A"]["after"] = ["B"]
        self.assertEqual(graph.topo_order(tickets), ["B", "A"])

    def test_after_never_overrides_blocks(self):
        tickets = {"A": t(), "B": t(blocked_by=[("A", "merge")]), "C": t()}
        tickets["A"]["after"] = ["C"]
        order = graph.topo_order(tickets)
        self.assertLess(order.index("A"), order.index("B"))
        self.assertLess(order.index("C"), order.index("A"))

    def test_after_cycle_does_not_raise(self):
        tickets = {"A": t(), "B": t()}
        tickets["A"]["after"] = ["B"]
        tickets["B"]["after"] = ["A"]
        self.assertEqual(graph.topo_order(tickets), ["A", "B"])
        warnings = graph.soft_warnings(tickets)
        self.assertEqual(len(warnings), 1)
        self.assertIn("soft precedence cycle", warnings[0])

    def test_human_ticket_needs_no_repo(self):
        tickets = {"H": t(repo=None)}
        tickets["H"]["kind"] = "human"
        self.assertEqual(graph.validate(tickets, "epic"), [])

    def test_unknown_after_and_related(self):
        tickets = {"A": t()}
        tickets["A"]["after"] = ["X"]
        tickets["A"]["related"] = ["Y"]
        errors = graph.validate(tickets, "epic")
        self.assertIn("ticket A: unknown after 'X'", errors)
        self.assertIn("ticket A: unknown related 'Y'", errors)

    def test_after_contradicts_blocks(self):
        tickets = {"A": t(), "B": t(blocked_by=[("A", "merge")])}
        tickets["A"]["after"] = ["B"]
        errors = graph.validate(tickets, "epic")
        self.assertIn("ticket A: after 'B' contradicts blocks", errors)

    def test_single_ticket_ships_with_group(self):
        tickets = {"A": t()}
        tickets["A"]["ships_with"] = "g1"
        errors = graph.validate(tickets, "epic")
        self.assertIn("ships_with group 'g1' has one ticket (A)", errors)


if __name__ == "__main__":
    unittest.main()
