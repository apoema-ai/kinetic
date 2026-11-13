"""Deterministic helpers for the discover phase: saved repo roots and GitHub
orgs, listing git repos under a root, and registering a repo in repos.json.
The judgment (which repos a ticket touches) lives in skills/discover."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from kinetic import config

SETTINGS = Path.home() / ".config/kinetic/settings.json"
REPOS = config.DEFAULT_CENTRAL


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def _real(p: str) -> str:
    return os.path.realpath(os.path.expanduser(p))


def settings(path=None) -> dict:
    data = config._load(Path(path or SETTINGS))
    return {"repo_roots": list(data.get("repo_roots") or []),
            "github_orgs": list(data.get("github_orgs") or [])}


def _merge(old: list, new: list) -> list:
    out = list(old)
    for x in new:
        if x not in out:
            out.append(x)
    return out


def remember(roots: list, orgs: list, path=None) -> dict:
    path = Path(path or SETTINGS)
    data = config._load(path)  # raises on bad JSON before anything is written
    real = [_real(r) for r in roots]
    bad = [r for r, rr in zip(roots, real) if not os.path.isdir(rr)]
    if bad:
        raise ValueError(f"not a directory: {', '.join(bad)}")
    data["repo_roots"] = _merge([_real(r) for r in data.get("repo_roots") or []], real)
    data["github_orgs"] = _merge(list(data.get("github_orgs") or []), [o.strip() for o in orgs if o.strip()])
    _write(path, data)
    return {"repo_roots": data["repo_roots"], "github_orgs": data["github_orgs"]}


def _git(path: str, *args) -> str | None:
    try:
        r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _item(path: str, registered: dict) -> dict:
    name = registered.get(path)
    return {"name": os.path.basename(path), "path": path,
            "remote": _git(path, "config", "--get", "remote.origin.url"),
            "registered": name is not None, "registered_as": name}


def scan(roots: list, central=None) -> list:
    entries = config._load(Path(central or REPOS))
    registered = {_real(e["path"]): n for n, e in entries.items()
                  if isinstance(e, dict) and e.get("path")}
    out, seen = [], set()

    def add(p):
        if p not in seen:
            seen.add(p)
            out.append(_item(p, registered))

    for root in roots:
        root = _real(root)
        if not os.path.isdir(root):
            continue
        top = _git(root, "rev-parse", "--show-toplevel")
        if top:
            add(_real(top))
            continue
        try:
            children = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError:
            continue
        for child in children:
            try:
                if child.is_dir() and os.path.exists(os.path.join(child.path, ".git")) \
                        and os.access(child.path, os.R_OK | os.X_OK):
                    add(_real(child.path))
            except OSError:
                continue
    return out


def register(name: str, path: str, verify: str, publish_snapshot=None, pin=None, central=None) -> dict:
    central = Path(central or REPOS)
    data = config._load(central)  # raises on bad JSON before anything is written
    if not (verify or "").strip():
        raise ValueError(f"no verify command for repo '{name}'")
    real = _real(path)
    if name in data:
        if _real(data[name].get("path", "")) != real:
            raise ValueError(f"repo '{name}' is already registered at {data[name].get('path')}")
        return data[name]
    entry = {"path": real, "verify": verify}
    if publish_snapshot:
        entry["publish_snapshot"] = publish_snapshot
    if pin:
        entry["pin"] = pin
    data[name] = entry
    _write(central, data)
    return entry


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.discover")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("settings")
    sp = sub.add_parser("remember")
    sp.add_argument("--root", action="append", default=[])
    sp.add_argument("--org", action="append", default=[])
    sp = sub.add_parser("scan")
    sp.add_argument("--root", action="append", required=True)
    sp = sub.add_parser("register")
    for a in ("--name", "--path", "--verify"):
        sp.add_argument(a, required=True)
    sp.add_argument("--publish-snapshot", default=None)
    sp.add_argument("--pin", default=None)
    a = p.parse_args(argv)
    try:
        if a.cmd == "settings":
            out = settings(SETTINGS)
        elif a.cmd == "remember":
            out = remember(a.root, a.org, SETTINGS)
        elif a.cmd == "scan":
            out = scan(a.root, REPOS)
        else:
            out = register(a.name, a.path, a.verify, a.publish_snapshot, a.pin, REPOS)
    except (ValueError, OSError, config.ConfigError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
