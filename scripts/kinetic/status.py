from __future__ import annotations

import argparse
import sys

from kinetic import frontier, state


def render(st: dict) -> str:
    out = [f"Lane: {st['lane']} | Phase: {st['phase']}", "",
           "| id | kind | repo | status | blocked by |", "| --- | --- | --- | --- | --- |"]
    for i, t in sorted(st["tickets"].items()):
        blockers = ", ".join(f"{e['id']} ({e['type']})" for e in t["blocked_by"]) or "—"
        out.append(f"| {i} | {state.field(t, 'kind')} | {t.get('repo') or '—'} | {t['status']} | {blockers} |")
    out += ["", "Waiting on you: " + (", ".join(frontier.waiting_on_you(st)) or "none"),
            "Ready: " + (", ".join(frontier.ready(st)) or "none"), "", "Gates:"]
    gates = st.get("gates") or {}
    out += [f"- {g}: {'yes' if v.get('approved') else 'no'}" for g, v in sorted(gates.items())]
    if not gates:
        out.append("- none recorded")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.status")
    p.add_argument("--run", required=True)
    a = p.parse_args(argv)
    try:
        print(render(state.load(a.run)), end="")
    except (ValueError, OSError, KeyError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
