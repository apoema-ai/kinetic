from __future__ import annotations

import os

import _common


def main(inp):
    found = _common.active_run(inp)
    ti = inp.get("tool_input") or {}
    paths = _common.tool_paths(ti)
    if not found or (not paths and ti.get("file_paths") is None):
        return
    # a patch tool whose headers did not parse cannot be checked -> ask
    if not paths:
        _common.pre_tool("ask", "kinetic could not parse the file paths in this patch; confirm manually")
        return
    run_dir, st = found
    # repos become writable only once the breakdown gate records the grant
    granted = ((st.get("gates") or {}).get("breakdown") or {}).get("approved")
    roots = [os.path.realpath(r["path"]) for r in st.get("repos", {}).values()] if granted else []
    roots.append(os.path.realpath(run_dir))
    for path in paths:
        real = os.path.realpath(_common.abs_path(path, inp.get("cwd")))
        if not any(real == r or real.startswith(r + os.sep) for r in roots):
            _common.pre_tool("deny", f"{real} is outside the run workspace. Allowed roots: " + ", ".join(roots))
            return


if __name__ == "__main__":
    _common.run(main, fail_closed=True)
