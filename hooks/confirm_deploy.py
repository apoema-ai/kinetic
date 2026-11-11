from __future__ import annotations

import _common


def main(inp):
    _common.pre_tool("ask", f"{inp.get('tool_name', 'deploy tool')} triggers a deploy; confirm with the user first")


if __name__ == "__main__":
    _common.run(main, fail_closed=True)
