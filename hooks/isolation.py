from __future__ import annotations

import os

import _common


def main(inp):
    found = _common.active_run(inp, tickets=False)
    ti = inp.get("tool_input") or {}
    paths = _common.tool_paths(ti)
    if not found or (not paths and ti.get("file_paths") is None):
        return
    # a patch tool whose headers did not parse cannot be checked -> ask
    if not paths:
        _common.pre_tool("ask", "kinetic could not parse the file paths in this patch; confirm manually")
        return
    run_dir, st = found
    # repos (and every worktree under the run) are writable only once the breakdown gate grants it;
    # approved covers runs recorded before granted_at existed
    gate = (st.get("gates") or {}).get("breakdown") or {}
    granted = gate.get("granted_at") or gate.get("approved")
    roots = [os.path.realpath(r["path"]) for r in st.get("repos", {}).values()] if granted else []
    roots.append(os.path.realpath(run_dir))
    worktrees = os.path.join(os.path.realpath(run_dir), "worktrees")
    for path in paths:
        real = os.path.realpath(_common.abs_path(path, inp.get("cwd")))
        if not granted and (real == worktrees or real.startswith(worktrees + os.sep)):
            _common.pre_tool("deny", f"{real} is a repo worktree; repos are read-only until the breakdown gate is approved")
            return
        if not any(real == r or real.startswith(r + os.sep) for r in roots):
            _common.pre_tool("deny", f"{real} is outside the run workspace. Allowed roots: " + ", ".join(roots))
            return


if __name__ == "__main__":
    _common.run(main, fail_closed=True)
