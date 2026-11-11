from __future__ import annotations

import _common


def main(inp):
    """After a Bash command that writes the active-run pointer, record its session as the owner."""
    cmd = str((inp.get("tool_input") or {}).get("command") or "")
    sid = inp.get("session_id")
    if not sid or "kinetic/active-run" not in cmd or "tee" not in cmd:
        return
    run_dir = _common.pointer_run_dir()
    if run_dir and _common.state is not None:
        _common.state.set_owner(run_dir, sid)


if __name__ == "__main__":
    _common.run(main)
