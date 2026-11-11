from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

try:
    from kinetic import state
except Exception:  # PreToolUse hooks fail closed via run(); others stay silent
    state = None


def read_input() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def active_run():
    """Return (run_dir, state) for the active run, or None.

    None only when there is no pointer or no state.json; a state.json that exists but cannot be
    loaded raises so fail-closed hooks can ask.
    """
    try:
        run_dir = (Path.home() / ".config" / "kinetic" / "active-run").read_text().strip()
    except OSError:
        return None
    if not run_dir or not os.path.isfile(os.path.join(run_dir, "state.json")):
        return None
    if state is None:
        raise ImportError("kinetic package not importable")
    return run_dir, state.load(run_dir)


def abs_path(path: str, cwd) -> str:
    return path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path)


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
