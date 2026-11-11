from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from kinetic import state  # noqa: E402


def read_input() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def active_run():
    """Return (run_dir, state) for the active run, or None."""
    try:
        run_dir = (Path.home() / ".config" / "kinetic" / "active-run").read_text().strip()
        if not run_dir or not os.path.isfile(os.path.join(run_dir, "state.json")):
            return None
        return run_dir, state.load(run_dir)
    except (OSError, ValueError):
        return None


def pre_tool(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision,
        "permissionDecisionReason": reason}}))


def run(fn, fail_closed: bool = False) -> None:
    """Run fn(input); never raise. fail_closed hooks ask when they cannot decide."""
    try:
        fn(read_input())
    except Exception as e:  # noqa: BLE001 - a hook must never crash a tool call
        if fail_closed:
            pre_tool("ask", f"kinetic hook could not decide ({type(e).__name__}); confirm manually")
    sys.exit(0)
