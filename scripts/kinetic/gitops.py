from __future__ import annotations

import argparse
import heapq
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kinetic import config, state


PUBLISHABLE = ("done", "done_with_concerns", "merged", "released")


def _git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def create_worktree(bare_or_repo, dest, branch: str, base: str) -> None:
    exists = _git(bare_or_repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    args = ["worktree", "add", str(dest), branch] if exists else \
        ["worktree", "add", "-b", branch, str(dest), base]
    r = _git(bare_or_repo, *args)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())


def merge_ticket(repo_path, ticket_branch: str, integration_branch: str) -> dict:
    co = _git(repo_path, "checkout", integration_branch)
    if co.returncode != 0:
        raise RuntimeError(co.stderr.strip())
    m = _git(repo_path, "merge", "--no-ff", "--no-edit", ticket_branch)
    if m.returncode == 0:
        return {"merged": True, "conflicts": []}
    out = _git(repo_path, "diff", "--name-only", "-z", "--diff-filter=U").stdout
    conflicts = sorted(f for f in out.split("\0") if f)
    if not conflicts:
        raise RuntimeError(m.stderr.strip() or m.stdout.strip())
    return {"merged": False, "conflicts": conflicts}


def merge_order(st: dict) -> list:
    """Repos ordered so a repo follows every repo it has a merge/release blocker in."""
    tickets = st["tickets"]
    repos = {t["repo"] for t in tickets.values() if t.get("repo")}
    before = {r: set() for r in repos}  # repo -> repos that must come first
    for t in tickets.values():
        if not t.get("repo"):
            continue
        for e in t["blocked_by"]:
            b = tickets.get(e["id"])
            if e["type"] in ("merge", "release") and b and b.get("repo") and b["repo"] != t["repo"]:
                before[t["repo"]].add(b["repo"])
    ready = [r for r, d in before.items() if not d]
    heapq.heapify(ready)
    order = []
    while ready:
        r = heapq.heappop(ready)
        order.append(r)
        for n, d in before.items():
            if r in d:
                d.discard(r)
                if not d:
                    heapq.heappush(ready, n)
    if len(order) != len(repos):
        raise ValueError("dependency cycle among repos: " + ", ".join(sorted(repos - set(order))))
    return order


def pin(run_dir, upstream_repo: str, downstream_repo: str, central=None) -> dict:
    repos = state.load(run_dir)["repos"]
    for name in (upstream_repo, downstream_repo):
        if name not in repos:
            raise ValueError(f"repo '{name}' not registered in state")
    up_path, down_path = Path(repos[upstream_repo]["path"]), Path(repos[downstream_repo]["path"])
    central = central or config.DEFAULT_CENTRAL
    publish = config.resolve(upstream_repo, up_path, central)["publish_snapshot"]
    pin_cmd = config.resolve(downstream_repo, down_path, central)["pin"]
    for name, cmd, key in ((upstream_repo, publish, "publish_snapshot"), (downstream_repo, pin_cmd, "pin")):
        if not cmd:
            return {"ok": False, "log_path": None, "reason": f"{key} command is unset for repo '{name}'"}
    head = _git(up_path, "rev-parse", "HEAD")
    ref = head.stdout.strip()
    if head.returncode != 0 or not ref:
        raise RuntimeError(head.stderr.strip() or f"cannot resolve HEAD in {up_path}")
    logs = Path(run_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = logs / f"pin-{upstream_repo}-{downstream_repo}-{ts}.log"
    env = {**os.environ, "KINETIC_UPSTREAM_REF": ref}
    with open(log_path, "wb") as log:
        ok = subprocess.run(publish, shell=True, cwd=str(up_path), stdout=log,
                            stderr=subprocess.STDOUT).returncode == 0
        if ok:
            ok = subprocess.run(pin_cmd, shell=True, cwd=str(down_path), env=env, stdout=log,
                                stderr=subprocess.STDOUT).returncode == 0
    if ok:
        for tid, t in state.load(run_dir)["tickets"].items():
            if t["repo"] == upstream_repo and t["status"] in PUBLISHABLE:
                state.set_ticket(run_dir, tid, snapshot_published=True)
    return {"ok": ok, "log_path": str(log_path)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.gitops")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worktree")
    w.add_argument("--repo", required=True)
    w.add_argument("--dest", required=True)
    w.add_argument("--branch", required=True)
    w.add_argument("--base", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--repo", required=True)
    m.add_argument("--ticket-branch", required=True)
    m.add_argument("--integration-branch", required=True)
    mo = sub.add_parser("merge-order")
    mo.add_argument("--run", required=True)
    pn = sub.add_parser("pin")
    pn.add_argument("--run", required=True)
    pn.add_argument("--upstream", required=True)
    pn.add_argument("--downstream", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "worktree":
            create_worktree(Path(a.repo), Path(a.dest), a.branch, a.base)
            out, rc = {"ok": True}, 0
        elif a.cmd == "merge":
            out = merge_ticket(Path(a.repo), a.ticket_branch, a.integration_branch)
            rc = 0 if out["merged"] else 1
        elif a.cmd == "merge-order":
            out, rc = {"order": merge_order(state.load(a.run))}, 0
        else:
            out = pin(a.run, a.upstream, a.downstream)
            rc = 0 if out["ok"] else 1
    except (ValueError, OSError, KeyError, RuntimeError, config.ConfigError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out))
    return rc


if __name__ == "__main__":
    sys.exit(main())
