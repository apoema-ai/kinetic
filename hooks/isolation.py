from __future__ import annotations

import os

import _common


def main(inp):
    found = _common.active_run()
    ti = inp.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not found or not path:
        return
    run_dir, st = found
    real = os.path.realpath(_common.abs_path(path, inp.get("cwd")))
    roots = [os.path.realpath(r["path"]) for r in st.get("repos", {}).values()]
    roots.append(os.path.realpath(run_dir))
    if any(real == r or real.startswith(r + os.sep) for r in roots):
        return
    _common.pre_tool("deny", f"{real} is outside the run workspace. Allowed roots: " + ", ".join(roots))


if __name__ == "__main__":
    _common.run(main, fail_closed=True)
