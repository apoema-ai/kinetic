from __future__ import annotations

import argparse
import json
import sys

from kinetic import graph, state

DONE = {"done", "done_with_concerns", "merged", "released"}
MERGED = {"merged", "released"}
# the orchestrator keeps these tickets' implementer and worktree alive
OCCUPYING = {"running", "needs_decision", "blocked"}


def _satisfied(edge: dict, blocker: dict) -> bool:
    st, typ = blocker["status"], edge["type"]
    if typ == "snapshot":
        return st in DONE and bool(blocker.get("snapshot_published"))
    if typ == "merge":
        return st in MERGED
    if typ == "release":
        return st == "released"
    return False


def ready(st: dict, cap: int = 3) -> list[str]:
    tickets = st["tickets"]
    try:
        order = graph.topo_order(tickets)
    except ValueError:
        return []  # cycle: the graph validator reports it, never dispatch into it
    running = [t for t in tickets.values() if t["status"] == "running"]
    busy = {t["repo"] for t in tickets.values() if t["status"] in OCCUPYING}
    out = []
    for i in order:
        if len(running) + len(out) >= cap:
            break
        t = tickets[i]
        if t["status"] != "todo" or not t.get("repo") or t["repo"] in busy:
            continue
        if all(e["id"] in tickets and _satisfied(e, tickets[e["id"]]) for e in t["blocked_by"]):
            out.append(i)
            busy.add(t["repo"])
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.frontier")
    p.add_argument("--run", required=True)
    p.add_argument("--cap", type=int, default=3)
    a = p.parse_args(argv)
    try:
        print(json.dumps({"ready": ready(state.load(a.run), a.cap)}))
    except (ValueError, OSError, KeyError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
