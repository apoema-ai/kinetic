from __future__ import annotations

import json
import os
import shlex

import _common

OCCUPIED = {"running", "needs_decision", "blocked"}


def _newest(verifies):
    return max(verifies, key=lambda v: v.get("at") or "", default=None)


def _stale(stamp, v):
    return v is None or (v.get("at") or "") <= stamp or v.get("exit_code") != 0


def main(inp):
    found = _common.active_run(inp)
    if inp.get("stop_hook_active") or not found:
        return
    run_dir, st = found
    verifies = list(st.get("verify", {}).values())
    bad = []
    for name, repo in st.get("repos", {}).items():
        stamp = repo.get("last_edit_at")
        if not stamp or any(t.get("repo") == name and t.get("status") in OCCUPIED
                            for t in st.get("tickets", {}).values()):
            continue
        if _stale(stamp, _newest([v for v in verifies if v.get("repo") == name])):
            tid = repo.get("last_edit_ticket")
            wt = st.get("tickets", {}).get(tid, {}).get("worktree") if tid else None
            bad.append((name, wt or repo.get("path"), tid if wt else None))
    top = st.get("last_edit_at")
    if top and _stale(top, _newest(verifies)):
        bad.append(("(outside registered repos)", None, None))
    if not bad:
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lines = []
    for name, path, tid in bad:
        if path:
            lines.append(f"{name}: PYTHONPATH={shlex.quote(root + '/scripts')} python3 -m kinetic.verify "
                         f"--run {shlex.quote(str(run_dir))} --repo-name {shlex.quote(name)} "
                         f"--repo-path {shlex.quote(path)}"
                         + (f" --ticket {shlex.quote(tid)}" if tid else ""))
        else:
            lines.append(f"{name}: run verify for the repo you edited")
    print(json.dumps({"decision": "block", "reason":
        "Run verify: no passing verify after the last edit. " + "; ".join(lines)}))


if __name__ == "__main__":
    _common.run(main)
