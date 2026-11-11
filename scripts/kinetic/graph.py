from __future__ import annotations

import argparse
import heapq
import json
import sys

from kinetic import state

EDGE_TYPES = ("snapshot", "merge", "release")


def topo_order(tickets: dict) -> list:
    """Blockers first, ties broken by ticket id. Edges to unknown ids are ignored."""
    indeg = {i: 0 for i in tickets}
    blocks = {i: [] for i in tickets}
    for i, t in tickets.items():
        for b in {e["id"] for e in t["blocked_by"] if e["id"] in tickets}:
            indeg[i] += 1
            blocks[b].append(i)
    ready = [i for i, d in indeg.items() if d == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        i = heapq.heappop(ready)
        order.append(i)
        for n in blocks[i]:
            indeg[n] -= 1
            if indeg[n] == 0:
                heapq.heappush(ready, n)
    if len(order) != len(tickets):
        stuck = sorted(set(tickets) - set(order))
        raise ValueError("dependency cycle among tickets: " + ", ".join(stuck))
    return order


def validate(tickets: dict, lane: str, slices: list | None = None) -> list:
    # lane is accepted per the interface; the brief gives it no behaviour.
    errors = []
    for i, t in sorted(tickets.items()):
        if not t.get("repo"):
            errors.append(f"ticket {i}: missing repo")
        for e in t["blocked_by"]:
            if e["type"] not in EDGE_TYPES:
                errors.append(f"ticket {i}: invalid edge type '{e['type']}' on blocker {e['id']} "
                              f"(expected one of {EDGE_TYPES})")
            if e["id"] not in tickets:
                errors.append(f"ticket {i}: unknown blocker '{e['id']}'")
    used = {t.get("slice") for t in tickets.values()}
    for s in slices or []:
        if s not in used:
            errors.append(f"slice {s}: no ticket references it")
    try:
        topo_order(tickets)
    except ValueError as e:
        errors.append(str(e))
    return errors


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.graph")
    p.add_argument("cmd", choices=("validate", "topo"))
    p.add_argument("--run", required=True)
    a = p.parse_args(argv)
    try:
        s = state.load(a.run)
        if a.cmd == "validate":
            errors = validate(s["tickets"], s["lane"], s.get("slices"))
            print(json.dumps({"errors": errors}))
            return 1 if errors else 0
        print(json.dumps({"order": topo_order(s["tickets"])}))
    except (ValueError, OSError, KeyError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
