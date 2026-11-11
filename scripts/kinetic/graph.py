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


def _upstream(tickets: dict, tid: str) -> set:
    """Every ticket tid is blocked by, directly or transitively."""
    seen, stack = set(), [tid]
    while stack:
        for e in tickets.get(stack.pop(), {}).get("blocked_by", []):
            if e["id"] in tickets and e["id"] not in seen:
                seen.add(e["id"])
                stack.append(e["id"])
    return seen


def interface_issues(tickets: dict) -> dict:
    """A consumer must be (transitively) blocked by every producer of what it consumes."""
    producers = {}
    for i, t in tickets.items():
        for name in t.get("produces") or []:
            producers.setdefault(name, set()).add(i)
    errors, warnings = [], []
    for i, t in sorted(tickets.items()):
        up = None
        for name in t.get("consumes") or []:
            prod = producers.get(name, set()) - {i}
            if not prod:
                if i not in producers.get(name, set()):
                    warnings.append(f"ticket {i}: consumes '{name}' that no ticket produces "
                                    f"(fine if it already exists)")
                continue
            up = _upstream(tickets, i) if up is None else up
            for p in sorted(prod - up):
                errors.append(f"ticket {i}: consumes '{name}' produced by {p} but has no edge to it")
    return {"errors": errors, "warnings": warnings}


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
    return errors + interface_issues(tickets)["errors"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.graph")
    p.add_argument("cmd", choices=("validate", "topo"))
    p.add_argument("--run", required=True)
    a = p.parse_args(argv)
    try:
        s = state.load(a.run)
        if a.cmd == "validate":
            errors = validate(s["tickets"], s["lane"], s.get("slices"))
            print(json.dumps({"errors": errors,
                              "warnings": interface_issues(s["tickets"])["warnings"]}))
            return 1 if errors else 0
        print(json.dumps({"order": topo_order(s["tickets"])}))
    except (ValueError, OSError, KeyError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
