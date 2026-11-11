from __future__ import annotations

import json

import _common
from kinetic import next_step


def main(inp):
    found = _common.active_run()
    if not found:
        return
    st = found[1]
    s = next_step.suggest(st)
    text = "\n".join([f"kinetic run {st['run_id']}", f"lane: {st['lane']}", f"phase: {st['phase']}",
                      f"next: {s['command']}", f"why: {s['reason']}"])
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                              "additionalContext": text}}))


if __name__ == "__main__":
    _common.run(main)
