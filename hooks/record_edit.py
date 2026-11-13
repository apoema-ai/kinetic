from __future__ import annotations

import _common


def main(inp):
    found = _common.active_run(inp, tickets=False)
    ti = inp.get("tool_input") or {}
    paths = _common.tool_paths(ti)
    if found:
        for path in paths:
            _common.state.record_edit(
                found[0], _common.abs_path(path, inp.get("cwd")))
    _common.touch_ticket(inp)


if __name__ == "__main__":
    _common.run(main)
