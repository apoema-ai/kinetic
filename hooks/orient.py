from __future__ import annotations

import json

import _common


def _one(s) -> str:
    return " ".join(str(s).split())


def main(inp):
    found = _common.active_run()  # orient every session, so a new one can resume
    if not found:
        return
    from kinetic import next_step
    st = found[1]
    s = next_step.suggest(st)
    text = "\n".join(_one(x) for x in (f"kinetic run {st['run_id']}", f"lane: {st['lane']}",
                                       f"phase: {st['phase']}", f"next: {s['command']}",
                                       f"why: {s['reason']}"))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                              "additionalContext": text}}))


if __name__ == "__main__":
    _common.run(main)
