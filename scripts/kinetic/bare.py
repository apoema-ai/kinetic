"""Bare-clone helpers: the saved bare_dir setting, recognising bare repos, and
listing the clones under it. Judgment (which folder to use) lives in the skills."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from kinetic import config, discover
from kinetic.discover import _real, _write

SETTINGS = discover.SETTINGS
LOCAL_MD = "bare-repos.local.md"
LOCAL_MD_SOURCE = "~/.claude/" + LOCAL_MD
SCAN_ROOTS = ["workspace", "code", "src", "dev", "projects", "repos", "git"]
SKIP_DIRS = {"node_modules", "Library", "target", "build", "dist", ".git"}
MAX_DEPTH = 3


def is_bare(path) -> bool:
    d = Path(path)
    if not (d / "HEAD").is_file() or not (d / "objects").is_dir() or not (d / "refs").is_dir():
        return False
    if (d / ".git").exists():
        return False
    try:
        return "bare = true" in (d / "config").read_text(errors="ignore").replace("\t", "")
    except OSError:
        return False


def _git(path, *args):
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def show(path=None):
    path = Path(path or SETTINGS)
    value = config._load(path).get("bare_dir")
    if value is None:
        return None
    if not isinstance(value, str):
        raise config.ConfigError(f"'bare_dir' in {path} must be a string")
    return value


def set_dir(d: str, create: bool = False, path=None) -> str:
    path = Path(path or SETTINGS)
    data = config._load(path)  # raises on bad JSON before anything is written
    real = _real(d)
    if not os.path.isdir(real):
        if not create:
            raise ValueError(f"not a directory: {d}")
        Path(real).mkdir(parents=True, exist_ok=True)
    data["bare_dir"] = real
    _write(path, data)
    return real


def default_branch(clone):
    return _git(clone, "symbolic-ref", "--short", "HEAD")


def list_clones(bare_dir) -> list:
    root = Path(bare_dir)
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir(), key=lambda c: c.name):
        if child.is_dir() and is_bare(child):
            out.append({"name": child.name, "path": str(child),
                        "remote": _git(child, "config", "--get", "remote.origin.url"),
                        "default_branch": default_branch(child)})
    return out


def _scan(home: Path) -> dict:
    found = {}
    for name in SCAN_ROOTS:
        root = home / name
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            try:
                children = sorted(c for c in d.iterdir() if c.is_dir() and not c.is_symlink())
            except OSError:
                continue
            for c in children:
                if is_bare(c):
                    found[d] = found.get(d, 0) + 1
                elif depth < MAX_DEPTH and c.name not in SKIP_DIRS and (
                        not c.name.startswith(".") or c.name == ".bare"):
                    stack.append((c, depth + 1))
    return found


def _cwd_container(cwd: Path):
    out = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not out:
        return None
    common = Path(out)
    return common.parent if is_bare(common) else None


def _local_md_hint(home: Path):
    p = home / ".claude" / LOCAL_MD
    try:
        lines = p.read_text().splitlines()
    except OSError:
        return None
    in_fm = False
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if i == 0:
                in_fm = True
                continue
            break
        if in_fm and ":" in line:
            k, v = line.split(":", 1)
            if k.strip() == "bare_repos_dir" and v.strip():
                val = v.strip()
                if val == "~" or val.startswith("~/"):
                    val = str(home) + val[1:]
                return os.path.abspath(val)
    return None


def detect(cwd, path=None, home=None) -> dict:
    home = Path(home) if home else Path.home()
    saved = show(path)
    candidates = []
    seen = set()

    def add(p, source, n):
        if p not in seen:
            seen.add(p)
            candidates.append({"path": p, "source": source, "bare_repo_count": n})

    from_cwd = _cwd_container(Path(_real(str(cwd))))
    scanned = sorted(_scan(home).items(), key=lambda kv: (-kv[1], str(kv[0])))
    hint = _local_md_hint(home)
    if hint:
        seen.add(hint)  # added last, below, so the 5-candidate cap cannot drop it
    if from_cwd:
        add(str(from_cwd), "current directory belongs to a bare repo",
            len(list_clones(str(from_cwd))))
    for p, n in scanned:
        add(str(p), "existing bare repos found", n)
    if hint:
        candidates = candidates[:4]
        candidates.append({"path": hint, "source": LOCAL_MD_SOURCE,
                           "bare_repo_count": len(list_clones(hint))})

    if saved:
        rec = {"path": saved, "reason": "already saved"}
    elif from_cwd:
        rec = {"path": str(from_cwd), "reason": "current directory belongs to a bare repo"}
    elif scanned:
        p, n = scanned[0]
        rec = {"path": str(p), "reason": f"existing bare repos found ({n} repos)"}
    elif hint:
        rec = {"path": hint, "reason": f"named in {LOCAL_MD_SOURCE}"}
    else:
        rec = None
    return {"saved": saved, "candidates": candidates[:5], "recommendation": rec}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.bare")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("detect")
    sp.add_argument("--cwd", default=None)
    sp = sub.add_parser("set")
    sp.add_argument("--dir", required=True)
    sp.add_argument("--create", action="store_true")
    sub.add_parser("show")
    sub.add_parser("list")
    a = p.parse_args(argv)
    try:
        if a.cmd == "detect":
            out = detect(a.cwd or os.getcwd(), SETTINGS)
        elif a.cmd == "set":
            out = {"bare_dir": set_dir(a.dir, a.create, SETTINGS)}
        else:
            d = show(SETTINGS)
            if d is None:
                print("no bare_dir saved; run 'kinetic bare set --dir PATH'", file=sys.stderr)
                return 1
            out = {"bare_dir": d} if a.cmd == "show" else list_clones(d)
    except (ValueError, OSError, config.ConfigError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
