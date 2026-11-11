from __future__ import annotations

import _common
from kinetic import state


def main(inp):
    found = _common.active_run()
    path = (inp.get("tool_input") or {}).get("file_path")
    if found and path:
        state.record_edit(found[0], path)


if __name__ == "__main__":
    _common.run(main)
