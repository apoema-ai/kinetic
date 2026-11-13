from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

LANES = ("quick", "feature", "epic")
STATUSES = ("todo", "running", "done", "done_with_concerns", "needs_decision",
            "blocked", "merged", "released")


PHASES = ("intake", "grill", "discover", "specify", "decompose", "build", "review", "ship", "retro", "done")
EDGE_TYPES = ("snapshot", "merge", "release")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _file(run_dir) -> Path:
    return Path(run_dir) / "state.json"


# phase names before 0.4.0; runs recorded in them read as the new names
OLD_PHASES = {"spec": "specify", "tickets": "decompose"}


def load(run_dir) -> dict:
    st = json.loads(_file(run_dir).read_text())
    if st.get("phase") in OLD_PHASES:
        st["phase"] = OLD_PHASES[st["phase"]]
    return st


def atomic_write(path, text: str) -> None:
    """Replace path with text via a same-dir temp file, keeping the file's mode (umask default if new)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = p.stat().st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)  # mkstemp creates 0600
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save(run_dir, state: dict) -> None:
    atomic_write(_file(run_dir), json.dumps(state, indent=2, sort_keys=True))


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


OCCUPIED = ("running", "needs_decision", "blocked")


def _verify_fresh(v, stamp) -> bool:
    """A verify record counts as fresh when it passed after stamp."""
    return bool(v) and (v.get("at") or "") > stamp and v.get("exit_code") == 0


def stale_verify(state: dict) -> list:
    """Repos whose verify is stale, by the same rule the stop gate uses:
    a repo edited after its newest verify record (or with no passing verify
    at all), skipping repos with occupied tickets. Also reports top-level
    edits outside every registered repo. Returns a list of
    {"repo", "path", "ticket"} dicts; repo/path/ticket are None for the
    outside-repos entry."""
    verifies = list(state.get("verify", {}).values())
    bad = []
    for name, repo in state.get("repos", {}).items():
        stamp = repo.get("last_edit_at")
        if not stamp or any(t.get("repo") == name and t.get("status") in OCCUPIED
                            for t in state.get("tickets", {}).values()):
            continue
        newest = max((v for v in verifies if v.get("repo") == name),
                     key=lambda v: v.get("at") or "", default=None)
        if not _verify_fresh(newest, stamp):
            tid = repo.get("last_edit_ticket")
            wt = state.get("tickets", {}).get(tid, {}).get("worktree") \
                if tid else None
            bad.append({"repo": name, "path": wt or repo.get("path"),
                        "ticket": tid if wt else None})
    top = state.get("last_edit_at")
    newest_all = max(verifies, key=lambda v: v.get("at") or "", default=None)
    if top and not _verify_fresh(newest_all, top):
        bad.append({"repo": None, "path": None, "ticket": None})
    return bad


def verify_command(run_dir, repo: str, path: str, ticket=None) -> str:
    """The `kinetic verify` remediation command for one stale_verify entry;
    shared by ship_refusal and the completion_gate Stop hook so both name
    the same command."""
    cmd = (f"kinetic verify --run {shlex.quote(str(run_dir))} "
           f"--repo-name {shlex.quote(repo)} "
           f"--repo-path {shlex.quote(path)}")
    if ticket:
        cmd += f" --ticket {shlex.quote(ticket)}"
    return cmd


def ship_refusal(state: dict, run_dir) -> str | None:
    """Why the run may not enter or approve the ship phase: verify is stale.
    Returns a remediation message or None. This is the CLI-level half of the
    verify-before-stop guarantee — harnesses without a Stop-block hook
    (OpenCode) rely on it, and it holds everywhere."""
    bad = stale_verify(state)
    if not bad:
        return None
    lines = []
    for b in bad:
        if b["repo"] is None:
            lines.append("edits outside registered repos: run verify for "
                         "the repo you edited")
        elif b["path"]:
            lines.append(verify_command(run_dir, b["repo"], b["path"],
                                        b["ticket"]))
        else:
            lines.append(f"{b['repo']}: run verify for the repo you edited")
    return ("verify is stale: no passing verify after the last edit. "
            + "; ".join(lines))


def set_phase(run_dir, phase: str) -> dict:
    phase = OLD_PHASES.get(phase, phase)
    if phase not in PHASES:
        raise ValueError(f"invalid phase '{phase}': expected one of {PHASES}")

    def fn(s):
        if phase == "ship":
            reason = ship_refusal(s, run_dir)
            if reason:
                raise ValueError(reason)
        s.update(phase=phase)

    return _mutate(run_dir, fn)


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


DONE_STATUSES = ("done", "done_with_concerns")


def done_refusal(state: dict, ticket_id: str):
    """Why ticket_id may not be marked done, or None: needs a passing verify newer than its edits."""
    v = state.get("verify", {}).get(ticket_id)
    if not v:
        return f"ticket {ticket_id}: no verify record; run kinetic.verify with --ticket {ticket_id}"
    if v.get("exit_code") != 0:
        return f"ticket {ticket_id}: last verify failed (exit {v.get('exit_code')}), log {v.get('log_path')}"
    repo = state.get("repos", {}).get(state["tickets"].get(ticket_id, {}).get("repo") or "", {})
    if repo.get("last_edit_ticket") == ticket_id and (repo.get("last_edit_at") or "") > (v.get("at") or ""):
        return f"ticket {ticket_id}: worktree edited after its last verify; re-run kinetic.verify"
    return None


KINDS = ("agent", "human")


def ticket_defaults() -> dict:
    return {
        "repo": None, "slice": None, "status": "todo", "blocked_by": [],
        "branch": None, "report": None, "snapshot_published": False,
        "kind": "agent", "after": [], "ships_with": None, "related": [],
        "human_note": None, "done_by": None,
    }


def field(t: dict, name: str):
    """Ticket field with the default for tickets written before the field existed."""
    return t.get(name, ticket_defaults()[name])


def _check_fields(fields: dict) -> None:
    if "kind" in fields and fields["kind"] not in KINDS:
        raise ValueError(f"invalid kind '{fields['kind']}': expected one of {KINDS}")
    for k in ("after", "related"):
        if k in fields and not (isinstance(fields[k], list) and all(isinstance(x, str) for x in fields[k])):
            raise ValueError(f"{k} must be a list of strings")
    if fields.get("ships_with") is not None and not isinstance(fields["ships_with"], str):
        raise ValueError("ships_with must be a string or null")


def set_ticket(run_dir, ticket_id: str, require_verify: bool = False, **fields) -> dict:
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"invalid status '{fields['status']}': expected one of {STATUSES}")
    if "blocked_by" in fields:
        _check_blocked_by(fields["blocked_by"])
    _check_fields(fields)

    def fn(state):
        existing = state["tickets"].get(ticket_id, {})
        if fields.get("status") in DONE_STATUSES:
            if fields.get("kind", field(existing, "kind")) == "human":
                raise ValueError(f"ticket {ticket_id} is a human ticket: mark it done with "
                                 "`kinetic.state human-done`")
            if require_verify:
                reason = done_refusal(state, ticket_id)
                if reason:
                    raise ValueError(reason)
        t = state["tickets"].setdefault(ticket_id, ticket_defaults())
        t.update(fields)

    return _mutate(run_dir, fn)


def human_done(run_dir, ticket_id: str, note: str | None = None) -> dict:
    def fn(state):
        t = state["tickets"].get(ticket_id)
        if t is None:
            raise ValueError(f"ticket {ticket_id} not found")
        if field(t, "kind") != "human":
            raise ValueError(f"ticket {ticket_id} is not kind=human; human-done applies only to human tickets")
        t.update(status="done", done_by="human", human_note=note)

    return _mutate(run_dir, fn)


def set_owner(run_dir, session_id: str) -> dict:
    """Record the Claude session that owns the run; hooks in other sessions ignore it."""
    return _mutate(run_dir, lambda s: s.update(owner_session=session_id))


def set_repo(run_dir, name: str, path: str, integration_branch: str) -> dict:
    def fn(state):
        state["repos"].setdefault(name, {}).update(
            {"path": str(path), "integration_branch": integration_branch})

    return _mutate(run_dir, fn)


def set_lane(run_dir, lane: str) -> dict:
    """Move between feature and epic (same phases); quick is fixed at intake."""
    if lane not in LANES:
        raise ValueError(f"invalid lane '{lane}': expected one of {LANES}")

    def fn(s):
        if lane != s["lane"] and "quick" in (lane, s["lane"]):
            raise ValueError(f"cannot change lane from {s['lane']} to {lane}: quick is fixed at intake")
        s["lane"] = lane

    return _mutate(run_dir, fn)


def remove_repo(run_dir, name: str) -> dict:
    def fn(s):
        if name not in s["repos"]:
            raise ValueError(f"repo '{name}' is not in the run")
        users = sorted(i for i, t in s["tickets"].items() if t.get("repo") == name)
        if users:
            raise ValueError(f"repo '{name}' is still named by tickets: {', '.join(users)}")
        del s["repos"][name]

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
                repo.pop("last_edit_ticket", None)
                return
        for tid, t in state["tickets"].items():
            wt = t.get("worktree")
            if wt and t.get("repo"):
                rp = os.path.realpath(wt)
                if real == rp or real.startswith(rp + os.sep):
                    r = state["repos"].setdefault(t["repo"], {})
                    r["last_edit_at"] = _now()
                    r["last_edit_ticket"] = tid  # so the gate hint can name the ticket worktree
                    return
        rd = os.path.realpath(run_dir)
        if real == rd or real.startswith(rd + os.sep):
            return  # R25: run-dir artifacts are not code
        state["last_edit_at"] = _now()

    _mutate(run_dir, fn)


def record_gate(run_dir, gate: str, approved: bool, note: str = "") -> None:
    def fn(s):
        if gate == "ship" and approved:
            reason = ship_refusal(s, run_dir)
            if reason:
                raise ValueError(reason)
        rec = {"approved": approved, "note": note, "at": _now()}
        # the breakdown grant, once given, survives a later rejection of a re-asked gate
        granted = (s["gates"].get(gate) or {}).get("granted_at")
        if gate == "breakdown" and (granted or approved):
            rec["granted_at"] = granted or rec["at"]
        s["gates"][gate] = rec

    _mutate(run_dir, fn)


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
    if v[:1] in ("[", "{") or (k == "snapshot_published" and v.lower() in ("true", "false")):
        try:
            return k, json.loads(v.lower() if k == "snapshot_published" else v)
        except ValueError:
            raise ValueError(f"invalid JSON for field '{k}': {v}")
    if v == "null" and k in ("ships_with", "human_note"):
        return k, None
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
    cmd("human-done", ("--id", {"required": True}), ("--note", {"default": None}))
    cmd("set-repo", ("--name", {"required": True}), ("--path", {"required": True}),
        ("--integration-branch", {"required": True}))
    cmd("set-lane", ("--lane", {"required": True}))
    cmd("remove-repo", ("--name", {"required": True}))
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
            out = set_ticket(a.run, a.id, require_verify=True, **fields)
        elif a.cmd == "human-done":
            out = human_done(a.run, a.id, a.note)
        elif a.cmd == "set-repo":
            out = set_repo(a.run, a.name, a.path, a.integration_branch)
        elif a.cmd == "set-lane":
            out = set_lane(a.run, a.lane)
        elif a.cmd == "remove-repo":
            out = remove_repo(a.run, a.name)
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
