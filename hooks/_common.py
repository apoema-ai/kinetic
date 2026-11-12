from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

try:
    from kinetic import state
except Exception:  # PreToolUse hooks fail closed via run(); others stay silent
    state = None

# The harness this hook invocation serves, selected by --harness (default claude,
# so existing hook commands keep working unchanged). Set by run() before fn runs.
_HARNESS = "claude"
# Mirrors kinetic.harness.HARNESS_IDS; used only when the kinetic package cannot
# be imported (e.g. hooks copied to a bare directory), where state is None anyway.
_KNOWN_HARNESSES = ("claude", "devin", "codex", "opencode")


def read_input() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _harness(argv=None) -> str:
    """Resolve --harness <id> from argv (manual parse: argparse would exit(2) on
    bad input, and a hook must never exit non-zero). Default claude; unknown ids
    warn on stderr and fall back to claude."""
    global _HARNESS
    args = list(sys.argv[1:] if argv is None else argv)
    hid = "claude"
    i = 0
    while i < len(args):
        if args[i] == "--harness" and i + 1 < len(args):
            hid, i = args[i + 1], i + 2
            continue
        if args[i].startswith("--harness="):
            hid = args[i].split("=", 1)[1]
        i += 1
    try:
        from kinetic import harness as profiles
        hid = profiles.profile(hid)["id"]  # validates against the profile table
    except Exception:
        if hid not in _KNOWN_HARNESSES:
            print(f"kinetic hook: unknown --harness '{hid}'; treating payload as claude",
                  file=sys.stderr)
            hid = "claude"
    _HARNESS = hid
    return hid


def _tool_aliases(harness: str) -> dict:
    """Map a harness's tool names onto the Claude names the hook logic reads
    ("Bash" for shell, "Write" for file edits). Built from the harness profile;
    claude needs no mapping and is never normalised."""
    try:
        from kinetic import harness as profiles
        tools = profiles.profile(harness)["tools"]
    except Exception:
        return {}
    aliases = {}
    if tools.get("shell"):
        aliases[tools["shell"]] = "Bash"
    edit_names = list(tools.get("edit") or [])
    if tools.get("patch") and tools["patch"] not in edit_names:
        edit_names.append(tools["patch"])
    for name in edit_names:
        aliases[name] = "Write"
    return aliases


def _norm_devin(inp: dict) -> dict:
    """Normalise a Devin CLI hook payload into the Claude shape the hooks read.

    Devin sends {hook_event_name, tool_name, tool_input, session_id, prompt_id}
    with no cwd — DEVIN_PROJECT_DIR carries the project root. Tool names differ
    (exec, edit, write); they are mapped through the harness profile. File tools
    may spell the path differently; canonicalise to file_path."""
    out = dict(inp)
    raw_ti = inp.get("tool_input")
    ti = dict(raw_ti) if isinstance(raw_ti, dict) else {}
    if not ti.get("file_path"):
        for key in ("path", "filePath", "target_path", "file"):
            if ti.get(key):
                ti["file_path"] = ti[key]
                break
    out["tool_input"] = ti
    name = out.get("tool_name")
    alias = _tool_aliases("devin").get(name)
    if alias:
        out["tool_name"] = alias
    if not out.get("cwd"):
        proj = os.environ.get("DEVIN_PROJECT_DIR")
        if proj:
            out["cwd"] = proj
    return out


# Codex's apply_patch grammar carries one or more file operations in
# tool_input.command: "*** Begin Patch", then "*** Add File: <path>",
# "*** Delete File: <path>", "*** Update File: <path>" headers and, inside an
# update hunk, "*** Move to: <path>". Paths are workspace-relative and may
# contain spaces; "*** Begin/End Patch" and "*** End of File" never match.
_PATCH_PATH = re.compile(
    r"^\*\*\*\s+(?:Add File|Delete File|Update File|Move to):"
    r"[ \t]*(\S.*?)\s*$",
    re.M)


def _patch_paths(command) -> list:
    """Ordered unique file paths referenced by a Codex apply_patch payload."""
    if not isinstance(command, str):
        return []
    seen, out = set(), []
    for m in _PATCH_PATH.finditer(command):
        path = m.group(1).strip()
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _norm_codex(inp: dict) -> dict:
    """Normalise a Codex CLI hook payload into the Claude shape the hooks read.

    Codex already sends session_id, cwd, tool_name and tool_input in the
    Claude-compatible field names, so only tool names need mapping (shell is
    "Bash", file edits are "apply_patch"). apply_patch carries the raw patch
    text in tool_input.command; every file header is extracted into
    tool_input.file_paths. The list is set even when empty so fail-closed
    hooks can tell "no paths parsed" apart from "not a patch tool"."""
    out = dict(inp)
    raw_ti = inp.get("tool_input")
    ti = dict(raw_ti) if isinstance(raw_ti, dict) else {}
    name = out.get("tool_name")
    alias = _tool_aliases("codex").get(name)
    if alias:
        out["tool_name"] = alias
    if name == "apply_patch":
        text = ti.get("command") or ti.get("patch") or ti.get("input") or ""
        ti["file_paths"] = _patch_paths(text)
    out["tool_input"] = ti
    return out


# Per-harness input normalisers. claude passes through untouched; codex and
# opencode arrive in their tickets. Codex adds apply_patch header parsing.
_NORMALIZERS = {"devin": _norm_devin, "codex": _norm_codex}


def _normalize(inp: dict, harness: str) -> dict:
    normalizer = _NORMALIZERS.get(harness)
    return normalizer(inp) if normalizer else inp


def pointer_run_dir():
    """The run dir the active-run pointer names, if it holds a state.json; else None."""
    try:
        run_dir = (Path.home() / ".config" / "kinetic" / "active-run").read_text().strip()
    except OSError:
        return None
    if not run_dir or not os.path.isfile(os.path.join(run_dir, "state.json")):
        return None
    return run_dir


def _in_scope(inp: dict, run_dir: str, st: dict) -> bool:
    owner, sid = st.get("owner_session"), inp.get("session_id")
    if not owner or not sid or sid == owner:
        return True
    # subagents may carry their own session id; work under the run dir is always in scope
    cwd, root = os.path.realpath(inp.get("cwd") or os.getcwd()), os.path.realpath(run_dir)
    return cwd == root or cwd.startswith(root + os.sep)


def active_run(inp=None):
    """Return (run_dir, state) for the active run if this hook call is in its scope, else None.

    In scope: the session that owns the run, any call whose cwd is inside the run dir, or every
    call when no owner is recorded or the payload has no session_id. A state.json that exists but
    cannot be loaded raises so fail-closed hooks can ask.
    """
    run_dir = pointer_run_dir()
    if run_dir is None:
        return None
    if state is None:
        raise ImportError("kinetic package not importable")
    st = state.load(run_dir)
    return (run_dir, st) if _in_scope(inp or {}, run_dir, st) else None


def abs_path(path: str, cwd) -> str:
    return path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path)


def _pre_tool_devin(decision: str, reason: str) -> None:
    if decision == "deny":
        # Devin's documented PreToolUse shape is a top-level decision; the
        # hookSpecificOutput copy covers Claude-format hook parsing (kinetic
        # installs on Devin as a Claude-format plugin, and top-level
        # decision:"block" also maps to deny there).
        print(json.dumps({
            "decision": "block", "reason": reason,
            "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}))
    else:
        # Devin has no "ask" decision (only approve/block). Emit the
        # Claude-format ask so a Claude-compatible parser prompts the user;
        # otherwise Devin's own permission flow decides, which prompts for
        # writes and exec in its default modes. Never emit decision:"approve".
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask",
            "permissionDecisionReason": reason}}))


def pre_tool(decision: str, reason: str) -> None:
    if _HARNESS == "devin":
        _pre_tool_devin(decision, reason)
    else:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": decision,
            "permissionDecisionReason": reason}}))


def run(fn, fail_closed: bool = False) -> None:
    """Run fn(input); never raise. fail_closed hooks ask when they cannot decide.

    --harness <id> selects the payload normaliser and the output shape; absent
    it defaults to claude so today's hook commands are unchanged.
    """
    harness = _harness()
    try:
        fn(_normalize(read_input(), harness))
    except Exception as e:  # noqa: BLE001 - a hook must never crash a tool call
        if fail_closed:
            pre_tool("ask", f"kinetic hook could not decide ({type(e).__name__}); confirm manually")
    sys.exit(0)
