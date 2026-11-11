from __future__ import annotations

import re
import shlex

import _common

SPLIT = re.compile(r"&&|\|\||;|\||\n")
PUSH = re.compile(r"^\s*(?:\w+=\S+\s+)*git\s+(?:(?:-c|-C)\s+\S+\s+|--\S+\s+)*push\b(.*)$", re.S)
GH_PR = re.compile(r"^\s*gh\s+pr\s+(create|merge|edit|ready)\b")


def _protected(args: str) -> str | None:
    try:
        toks = shlex.split(args)
    except ValueError:
        toks = args.split()
    for t in toks:
        if t.startswith("-"):
            continue
        ref = t.lstrip("+").rsplit(":", 1)[-1]
        if ref.startswith("refs/heads/"):
            ref = ref[len("refs/heads/"):]
        if ref in ("main", "master") or ref.startswith("Release"):
            return ref
    return None


def main(inp):
    if inp.get("tool_name") != "Bash":
        _common.pre_tool("ask", f"{inp.get('tool_name')} changes an external system; confirm with the user first")
        return
    cmd = (inp.get("tool_input") or {}).get("command") or ""
    ask = None
    for seg in SPLIT.split(cmd):
        m = PUSH.match(seg)
        if m:
            ref = _protected(m.group(1))
            if ref:
                _common.pre_tool("deny", f"git push to protected branch '{ref}' is not allowed; use a feature branch and a PR")
                return
            ask = "git push publishes commits; confirm with the user first"
        elif GH_PR.match(seg):
            ask = ask or "gh pr changes a pull request; confirm with the user first"
    if ask:
        _common.pre_tool("ask", ask)


if __name__ == "__main__":
    _common.run(main, fail_closed=True)
