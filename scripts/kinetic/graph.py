from __future__ import annotations

import argparse
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
    after = {i: [x for x in state.field(t, "after") if x in tickets] for i, t in tickets.items()}
    order, placed = [], set()
    while len(order) < len(tickets):
        ready = sorted(i for i in tickets if i not in placed and indeg[i] == 0)
        if not ready:
            break
        # soft tie-break: prefer tickets whose `after` targets are placed; a soft cycle falls back to smallest id
        i = next((r for r in ready if all(x in placed for x in after[r])), ready[0])
        order.append(i)
        placed.add(i)
        for n in blocks[i]:
            indeg[n] -= 1
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


def soft_warnings(tickets: dict) -> list:
    """Tickets whose `after` links lead back to themselves."""
    after = {i: [x for x in state.field(t, "after") if x in tickets] for i, t in tickets.items()}
    cyc = []
    for i in sorted(tickets):
        seen, stack = set(), list(after[i])
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack.extend(after[x])
        if i in seen:
            cyc.append(i)
    return ["soft precedence cycle among: " + ", ".join(cyc)] if cyc else []


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


def validate(tickets: dict, lane: str, slices: list | None = None, repos: dict | None = None) -> list:
    # lane is accepted per the interface; the brief gives it no behaviour.
    errors = []
    for i, t in sorted(tickets.items()):
        if state.field(t, "kind") != "human" and not t.get("repo"):
            errors.append(f"ticket {i}: missing repo")
        elif repos is not None and state.field(t, "kind") != "human" and t["repo"] not in repos:
            errors.append(f"ticket {i}: repo '{t['repo']}' is not in the run; run discover for it")
        for x in state.field(t, "after"):
            if x not in tickets:
                errors.append(f"ticket {i}: unknown after '{x}'")
            elif i in _upstream(tickets, x):
                errors.append(f"ticket {i}: after '{x}' contradicts blocks")
        for x in state.field(t, "related"):
            if x not in tickets:
                errors.append(f"ticket {i}: unknown related '{x}'")
        for e in t["blocked_by"]:
            if e["type"] not in EDGE_TYPES:
                errors.append(f"ticket {i}: invalid edge type '{e['type']}' on blocker {e['id']} "
                              f"(expected one of {EDGE_TYPES})")
            if e["id"] not in tickets:
                errors.append(f"ticket {i}: unknown blocker '{e['id']}'")
    groups = {}
    for i, t in sorted(tickets.items()):
        if state.field(t, "ships_with"):
            groups.setdefault(state.field(t, "ships_with"), []).append(i)
    for g, members in sorted(groups.items()):
        if len(members) == 1:
            errors.append(f"ships_with group '{g}' has one ticket ({members[0]})")
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
            errors = validate(s["tickets"], s["lane"], s.get("slices"), s.get("repos", {}))
            print(json.dumps({"errors": errors,
                              "warnings": interface_issues(s["tickets"])["warnings"]
                              + soft_warnings(s["tickets"])}))
            return 1 if errors else 0
        print(json.dumps({"order": topo_order(s["tickets"])}))
    except (ValueError, OSError, KeyError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
