from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from kinetic import frontier, state

DONE = {"done", "done_with_concerns", "merged", "released"}


def active_run_file() -> Path:
    return Path(os.path.expanduser("~")) / ".config" / "kinetic" / "active-run"


def _r(command: str, reason: str) -> dict:
    return {"command": command, "reason": reason}


def suggest(st: dict | None) -> dict:
    if st is None:
        return _r("/kinetic:run <ref>", "no active run")
    tickets = st["tickets"]
    deciding = sorted(i for i, t in tickets.items() if t["status"] == "needs_decision")
    if deciding:
        return _r("/kinetic:run", f"ticket {deciding[0]} needs a decision")
    stale = state.stale_running(st, Path(st["run_dir"]) / "reports")
    if stale:
        return _r("/kinetic:run", "recover " + ", ".join(stale))
    if st["phase"] == "build":
        ready = frontier.ready(st)
        if ready:
            return _r("/kinetic:run", f"{len(ready)} tickets ready")
        if tickets and all(t["status"] in DONE for t in tickets.values()):
            return _r("/kinetic:run", "review and ship")
    if st["phase"] == "ship" and st["gates"].get("ship", {}).get("approved"):
        return _r("/kinetic:run", "retro")
    return _r("/kinetic:status", "check the board")


def _load_active() -> dict | None:
    try:
        run_dir = active_run_file().read_text().strip()
    except OSError:
        return None
    if not run_dir:
        return None
    try:
        return state.load(run_dir)
    except OSError:
        return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.next_step")
    p.add_argument("--run", default=None)
    a = p.parse_args(argv)
    try:
        st = state.load(a.run) if a.run else _load_active()
        print(json.dumps(suggest(st)))
    except (ValueError, OSError, KeyError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
