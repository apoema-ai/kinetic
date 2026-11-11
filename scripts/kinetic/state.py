from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

LANES = ("quick", "feature", "epic")
STATUSES = ("todo", "running", "done", "done_with_concerns", "needs_decision",
            "blocked", "merged", "released")


PHASES = ("intake", "grill", "spec", "tickets", "build", "review", "ship", "retro", "done")
EDGE_TYPES = ("snapshot", "merge", "release")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _file(run_dir) -> Path:
    return Path(run_dir) / "state.json"


def load(run_dir) -> dict:
    return json.loads(_file(run_dir).read_text())


def save(run_dir, state: dict) -> None:
    f = _file(run_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(f.parent), prefix="state.json.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, f)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _mutate(run_dir, fn) -> dict:
    """Exclusive-locked load -> fn(state) -> save; returns the saved state."""
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(run_dir) / "state.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load(run_dir)
        fn(state)
        save(run_dir, state)
        return state


def init(run_dir, lane: str, ref: str, force: bool = False) -> dict:
    if lane not in LANES:
        raise ValueError(f"invalid lane '{lane}': expected one of {LANES}")
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": uuid.uuid4().hex[:12], "run_dir": str(run_dir), "lane": lane,
        "ref": ref, "phase": "intake", "tickets": {}, "slices": [], "repos": {},
        "gates": {}, "rulings": [], "verify": {}, "last_edit_at": None,
    }
    with open(Path(run_dir) / "state.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _file(run_dir).exists() and not force:
            raise FileExistsError(f"state already exists in {run_dir}; use force to overwrite")
        save(run_dir, state)
    return state


def set_phase(run_dir, phase: str) -> dict:
    if phase not in PHASES:
        raise ValueError(f"invalid phase '{phase}': expected one of {PHASES}")
    return _mutate(run_dir, lambda s: s.update(phase=phase))


def set_slices(run_dir, slices: list) -> dict:
    if not isinstance(slices, list) or not all(isinstance(s, str) and s for s in slices):
        raise ValueError("slices must be a list of non-empty strings")
    return _mutate(run_dir, lambda s: s.update(slices=list(slices)))


def _check_blocked_by(entries) -> None:
    if not isinstance(entries, list):
        raise ValueError("blocked_by must be a list")
    for e in entries:
        if not isinstance(e, dict) or "id" not in e or e.get("type") not in EDGE_TYPES:
            raise ValueError(f"invalid blocked_by entry {e!r}: need id and type in {EDGE_TYPES}")


def set_ticket(run_dir, ticket_id: str, **fields) -> dict:
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"invalid status '{fields['status']}': expected one of {STATUSES}")
    if "blocked_by" in fields:
        _check_blocked_by(fields["blocked_by"])

    def fn(state):
        t = state["tickets"].setdefault(ticket_id, {
            "repo": None, "slice": None, "status": "todo", "blocked_by": [],
            "branch": None, "report": None, "snapshot_published": False,
        })
        t.update(fields)

    return _mutate(run_dir, fn)


def set_repo(run_dir, name: str, path: str, integration_branch: str) -> dict:
    def fn(state):
        state["repos"].setdefault(name, {}).update(
            {"path": str(path), "integration_branch": integration_branch})

    return _mutate(run_dir, fn)


def record_verify(run_dir, ticket_id, exit_code: int, log_path: str, repo_name=None,
                  at: str | None = None) -> None:
    if ticket_id is None and not repo_name:
        raise ValueError("repo_name is required when ticket_id is None")
    key = ticket_id if ticket_id is not None else f"repo:{repo_name}"
    stamp = at or _now()

    def fn(s):
        repo = repo_name or s["tickets"].get(ticket_id, {}).get("repo")
        s["verify"][key] = {"exit_code": exit_code, "log_path": log_path, "at": stamp,
                            "repo": repo}
    _mutate(run_dir, fn)


def record_edit(run_dir, path: str) -> None:
    real = os.path.realpath(path)

    def fn(state):
        for repo in state["repos"].values():
            rp = os.path.realpath(repo["path"])
            if real == rp or real.startswith(rp + os.sep):
                repo["last_edit_at"] = _now()
                return
        for t in state["tickets"].values():
            wt = t.get("worktree")
            if wt and t.get("repo"):
                rp = os.path.realpath(wt)
                if real == rp or real.startswith(rp + os.sep):
                    state["repos"].setdefault(t["repo"], {})["last_edit_at"] = _now()
                    return
        rd = os.path.realpath(run_dir)
        if real == rd or real.startswith(rd + os.sep):
            return  # R25: run-dir artifacts are not code
        state["last_edit_at"] = _now()

    _mutate(run_dir, fn)


def record_gate(run_dir, gate: str, approved: bool, note: str = "") -> None:
    _mutate(run_dir, lambda s: s["gates"].__setitem__(
        gate, {"approved": approved, "note": note, "at": _now()}))


def add_ruling(run_dir, what: str, why: str, cost: str) -> None:
    _mutate(run_dir, lambda s: s["rulings"].append(
        {"what": what, "why": why, "cost": cost, "at": _now()}))


def stale_running(state: dict, reports_dir) -> list:
    return [i for i, t in state["tickets"].items()
            if t["status"] == "running" and not (Path(reports_dir) / f"{i}.md").is_file()]


def _bool(v: str) -> bool:
    if v.lower() in ("1", "true", "yes", "y"):
        return True
    if v.lower() in ("0", "false", "no", "n"):
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean '{v}'")


def _parse_field(kv: str):
    k, sep, v = kv.partition("=")
    if not sep or not k:
        raise ValueError(f"invalid --field '{kv}': expected KEY=VALUE")
    if v[:1] in ("[", "{") or (k == "snapshot_published" and v in ("true", "false")):
        try:
            return k, json.loads(v)
        except ValueError:
            raise ValueError(f"invalid JSON for field '{k}': {v}")
    return k, v


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.state")
    sub = p.add_subparsers(dest="cmd", required=True)

    def cmd(name, *args):
        sp = sub.add_parser(name)
        sp.add_argument("--run", required=True)
        for a, kw in args:
            sp.add_argument(a, **kw)

    cmd("init", ("--lane", {"required": True}), ("--ref", {"required": True}),
        ("--force", {"action": "store_true"}))
    cmd("set-phase", ("--phase", {"required": True}))
    cmd("load")
    cmd("set-slices", ("--slices", {"required": True, "metavar": "JSON_LIST"}))
    cmd("set-ticket", ("--id", {"required": True}),
        ("--field", {"action": "append", "default": [], "metavar": "KEY=VALUE"}))
    cmd("set-repo", ("--name", {"required": True}), ("--path", {"required": True}),
        ("--integration-branch", {"required": True}))
    cmd("record-verify", ("--ticket", {"default": None}), ("--exit-code", {"type": int, "required": True}),
        ("--log-path", {"required": True}), ("--repo-name", {"default": None}),
        ("--at", {"default": None}))
    cmd("record-edit", ("--path", {"required": True}))
    cmd("record-gate", ("--gate", {"required": True}), ("--approved", {"type": _bool, "required": True}),
        ("--note", {"default": ""}))
    cmd("add-ruling", ("--what", {"required": True}), ("--why", {"required": True}),
        ("--cost", {"required": True}))
    cmd("stale-running")

    a = p.parse_args(argv)
    try:
        if a.cmd == "init":
            out = init(Path(a.run), a.lane, a.ref, a.force)
        elif a.cmd == "set-phase":
            out = set_phase(a.run, a.phase)
        elif a.cmd == "load":
            out = load(a.run)
        elif a.cmd == "set-slices":
            out = set_slices(a.run, json.loads(a.slices))
        elif a.cmd == "set-ticket":
            fields = dict(_parse_field(kv) for kv in a.field)
            out = set_ticket(a.run, a.id, **fields)
        elif a.cmd == "set-repo":
            out = set_repo(a.run, a.name, a.path, a.integration_branch)
        elif a.cmd == "record-verify":
            record_verify(a.run, a.ticket, a.exit_code, a.log_path, a.repo_name, a.at)
            out = load(a.run)["verify"]
        elif a.cmd == "record-edit":
            record_edit(a.run, a.path)
            out = {"last_edit_at": load(a.run)["last_edit_at"]}
        elif a.cmd == "record-gate":
            record_gate(a.run, a.gate, a.approved, a.note)
            out = load(a.run)["gates"]
        elif a.cmd == "add-ruling":
            add_ruling(a.run, a.what, a.why, a.cost)
            out = load(a.run)["rulings"]
        else:
            out = stale_running(load(a.run), Path(a.run) / "reports")
    except (ValueError, OSError, KeyError, FileExistsError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
