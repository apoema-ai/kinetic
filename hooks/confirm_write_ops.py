from __future__ import annotations

import os
import re

import _common

TOKEN = re.compile(r"&&|\|\||[;&|]|[^\s'\"()&;|`$]+")
SEPARATORS = {"&&", "||", ";", "&", "|"}
NON_PUSH = {"status", "diff", "log", "show", "add", "commit", "checkout", "switch", "branch", "fetch",
            "pull", "merge", "rebase", "worktree", "rev-parse", "rev-list", "config", "stash", "tag",
            "remote", "init", "clone", "restore", "reset", "grep", "ls-files", "blame", "cherry-pick",
            "merge-base", "ls-remote", "cat-file", "show-ref", "for-each-ref", "describe", "rm", "mv",
            "cherry", "name-rev", "show-branch", "symbolic-ref", "ls-tree", "reflog", "shortlog", "clean"}
OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
GH_PR = re.compile(r"\bgh\s+pr\s+(create|merge|edit|ready)\b")
ANY_PUSH = re.compile(r"\bgit\b[\s\S]*\bpush\b")
BRANCH_WRITES = re.compile(r"push_files|create_or_update_file|delete_file")


def _is_protected(name: str) -> bool:
    return name in ("main", "master") or name.startswith("Release")


def _protected_arg(tok: str) -> bool:
    if tok in ("--all", "--mirror"):
        return True
    if tok.startswith("-"):
        return False
    for part in tok.lstrip("+:").split(":"):
        part = part.lstrip("+")
        if part.startswith("refs/heads/"):
            part = part[len("refs/heads/"):]
        if _is_protected(part):
            return True
    return False


def _git_calls(cmd: str):
    """Yield (subcommand, args) for every git invocation found in cmd."""
    toks = TOKEN.findall(cmd)
    for i, t in enumerate(toks):
        if os.path.basename(t) != "git":
            continue
        j = i + 1
        while j < len(toks) and toks[j].startswith("-"):
            j += 2 if toks[j] in OPT_WITH_ARG else 1
        if j >= len(toks) or toks[j] in SEPARATORS:
            continue
        k = j + 1
        while k < len(toks) and toks[k] not in SEPARATORS:
            k += 1
        yield toks[j], toks[j + 1:k]


def classify_bash(cmd: str):
    # the shell concatenates quoted pieces (gi''t -> git), so drop quote chars before matching
    cmd = re.sub(r"['\"\\]", "", cmd)
    ask = bool(GH_PR.search(cmd) or ANY_PUSH.search(cmd))
    for sub, args in _git_calls(cmd):
        if sub in NON_PUSH:
            continue
        ask = True
        if any(_protected_arg(a) for a in args):
            return "deny", "git push to a protected branch (main, master, Release*) is not allowed; use a feature branch and a PR"
    if ask:
        return "ask", "this command pushes or changes a pull request; confirm with the user first"
    return None


def main(inp):
    name = inp.get("tool_name") or ""
    ti = inp.get("tool_input") or {}
    if name == "Bash":
        r = classify_bash(ti.get("command") or "")
        if r:
            _common.pre_tool(*r)
        return
    if BRANCH_WRITES.search(name) and _is_protected(str(ti.get("branch") or "")):
        _common.pre_tool("deny", f"{name} on protected branch '{ti.get('branch')}' is not allowed")
        return
    _common.pre_tool("ask", f"{name} changes an external system; confirm with the user first")


if __name__ == "__main__":
    _common.run(main, fail_closed=True)
