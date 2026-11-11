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


def pointer_run_dir():
    """The run dir the active-run pointer names, if it holds a state.json; else None."""
    try:
        run_dir = (Path.home() / ".config" / "kinetic" / "active-run").read_text().strip()
    except OSError:
        return None
    if not run_dir or not os.path.isfile(os.path.join(run_dir, "state.json")):
        return None
    return run_dir


def _in_scope(inp: dict, run_dir: str, st: dict) -> bool:
    owner, sid = st.get("owner_session"), inp.get("session_id")
    if not owner or not sid or sid == owner:
        return True
    # subagents may carry their own session id; work under the run dir is always in scope
    cwd, root = os.path.realpath(inp.get("cwd") or os.getcwd()), os.path.realpath(run_dir)
    return cwd == root or cwd.startswith(root + os.sep)


def active_run(inp=None):
    """Return (run_dir, state) for the active run if this hook call is in its scope, else None.

    In scope: the session that owns the run, any call whose cwd is inside the run dir, or every
    call when no owner is recorded or the payload has no session_id. A state.json that exists but
    cannot be loaded raises so fail-closed hooks can ask.
    """
    run_dir = pointer_run_dir()
    if run_dir is None:
        return None
    if state is None:
        raise ImportError("kinetic package not importable")
    st = state.load(run_dir)
    return (run_dir, st) if _in_scope(inp or {}, run_dir, st) else None


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
