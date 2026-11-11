from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

LANES = ("quick", "feature", "epic")
STATUSES = ("todo", "running", "done", "done_with_concerns", "needs_decision",
            "blocked", "merged", "released")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file(run_dir) -> Path:
    return Path(run_dir) / "state.json"


def load(run_dir) -> dict:
    return json.loads(_file(run_dir).read_text())


def save(run_dir, state: dict) -> None:
    f = _file(run_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    os.replace(tmp, f)


def init(run_dir, lane: str, ref: str) -> dict:
    if lane not in LANES:
        raise ValueError(f"invalid lane '{lane}': expected one of {LANES}")
    state = {
        "run_id": uuid.uuid4().hex[:12], "run_dir": str(run_dir), "lane": lane,
        "ref": ref, "phase": "intake", "tickets": {}, "slices": [], "repos": {},
        "gates": {}, "rulings": [], "verify": {}, "last_edit_at": None,
    }
    save(run_dir, state)
    return state


def set_ticket(run_dir, ticket_id: str, **fields) -> dict:
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"invalid status '{fields['status']}': expected one of {STATUSES}")
    state = load(run_dir)
    t = state["tickets"].setdefault(ticket_id, {
        "repo": None, "slice": None, "status": "todo", "blocked_by": [],
        "branch": None, "report": None, "snapshot_published": False,
    })
    t.update(fields)
    save(run_dir, state)
    return state


def set_repo(run_dir, name: str, path: str, integration_branch: str) -> dict:
    state = load(run_dir)
    state["repos"][name] = {"path": str(path), "integration_branch": integration_branch}
    save(run_dir, state)
    return state


def record_verify(run_dir, ticket_id, exit_code: int, log_path: str, repo_name=None) -> None:
    if ticket_id is None and not repo_name:
        raise ValueError("repo_name is required when ticket_id is None")
    state = load(run_dir)
    key = ticket_id if ticket_id is not None else f"repo:{repo_name}"
    state["verify"][key] = {"exit_code": exit_code, "log_path": log_path, "at": _now()}
    save(run_dir, state)


def record_edit(run_dir, path: str) -> None:
    state = load(run_dir)
    state["last_edit_at"] = _now()
    save(run_dir, state)


def record_gate(run_dir, gate: str, approved: bool, note: str = "") -> None:
    state = load(run_dir)
    state["gates"][gate] = {"approved": approved, "note": note, "at": _now()}
    save(run_dir, state)


def add_ruling(run_dir, what: str, why: str, cost: str) -> None:
    state = load(run_dir)
    state["rulings"].append({"what": what, "why": why, "cost": cost, "at": _now()})
    save(run_dir, state)


def stale_running(state: dict, reports_dir) -> list:
    return [i for i, t in state["tickets"].items()
            if t["status"] == "running" and not (Path(reports_dir) / f"{i}.md").is_file()]


def _bool(v: str) -> bool:
    return v.lower() in ("1", "true", "yes", "y")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.state")
    sub = p.add_subparsers(dest="cmd", required=True)

    def cmd(name, *args):
        sp = sub.add_parser(name)
        sp.add_argument("--run", required=True)
        for a, kw in args:
            sp.add_argument(a, **kw)

    cmd("init", ("--lane", {"required": True}), ("--ref", {"required": True}))
    cmd("load")
    cmd("set-ticket", ("--id", {"required": True}),
        ("--field", {"action": "append", "default": [], "metavar": "KEY=VALUE"}))
    cmd("set-repo", ("--name", {"required": True}), ("--path", {"required": True}),
        ("--integration-branch", {"required": True}))
    cmd("record-verify", ("--ticket", {"default": None}), ("--exit-code", {"type": int, "required": True}),
        ("--log-path", {"required": True}), ("--repo-name", {"default": None}))
    cmd("record-edit", ("--path", {"required": True}))
    cmd("record-gate", ("--gate", {"required": True}), ("--approved", {"type": _bool, "required": True}),
        ("--note", {"default": ""}))
    cmd("add-ruling", ("--what", {"required": True}), ("--why", {"required": True}),
        ("--cost", {"required": True}))
    cmd("stale-running")

    a = p.parse_args(argv)
    try:
        if a.cmd == "init":
            out = init(Path(a.run), a.lane, a.ref)
        elif a.cmd == "load":
            out = load(a.run)
        elif a.cmd == "set-ticket":
            fields = {}
            for kv in a.field:
                k, _, v = kv.partition("=")
                # JSON-decode values (lists, bools); fall back to plain string
                try:
                    fields[k] = json.loads(v)
                except ValueError:
                    fields[k] = v
            out = set_ticket(a.run, a.id, **fields)
        elif a.cmd == "set-repo":
            out = set_repo(a.run, a.name, a.path, a.integration_branch)
        elif a.cmd == "record-verify":
            record_verify(a.run, a.ticket, a.exit_code, a.log_path, a.repo_name)
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
    except (ValueError, OSError, KeyError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
