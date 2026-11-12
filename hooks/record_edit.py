from __future__ import annotations

import _common


def _paths(ti):
    """File paths a tool call touched: a list for multi-file tools
    (Codex apply_patch), else the single file_path/notebook_path."""
    paths = ti.get("file_paths")
    if paths is not None:
        return list(paths)
    path = ti.get("file_path") or ti.get("notebook_path")
    return [path] if path else []


def main(inp):
    found = _common.active_run(inp)
    ti = inp.get("tool_input") or {}
    paths = _paths(ti)
    if found:
        for path in paths:
            _common.state.record_edit(
                found[0], _common.abs_path(path, inp.get("cwd")))


if __name__ == "__main__":
    _common.run(main)
