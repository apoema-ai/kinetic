from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from kinetic import config

SKILLS = ["find-ticket-repos", "checkout-ticket-repos", "resolving-merge-conflicts"]
PLUGINS = ["superpowers", "dev-fleet"]


def _r(name: str, status: str, fix: str = "") -> dict:
    return {"name": name, "status": status, "fix": fix}


def _central_check(central: Path) -> dict:
    if not central.is_file():
        return _r("central-config", "warn", f"run /kinetic:init to create {central}")
    try:
        ok = isinstance(json.loads(central.read_text()), dict)
    except (ValueError, OSError):
        ok = False
    if not ok:
        return _r("central-config", "fail", f"fix {central}: must be a JSON object")
    return _r("central-config", "pass")


def checks(repos: list[tuple[str, str]], home: Path | None = None,
           central: Path | None = None) -> list[dict]:
    home = Path(home) if home else Path.home()
    central = Path(central) if central else config.DEFAULT_CENTRAL
    out = []
    for tool in ("git", "gh"):
        found = shutil.which(tool)
        out.append(_r(tool, "pass") if found else _r(tool, "fail", f"install {tool} and put it on PATH"))
    if shutil.which("gh"):
        try:
            code = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=10).returncode
        except (subprocess.TimeoutExpired, OSError):
            code = 1
        out.append(_r("gh-auth", "pass") if code == 0 else _r("gh-auth", "fail", "run: gh auth login"))
    out.append(_central_check(central))
    for name, path in repos:
        try:
            config.resolve(name, Path(path), central)
            out.append(_r(f"verify:{name}", "pass"))
        except (config.ConfigError, ValueError, OSError, AttributeError) as e:
            out.append(_r(f"verify:{name}", "fail", str(e)))
    for s in SKILLS:
        ok = (home / ".claude/skills" / s / "SKILL.md").is_file()
        out.append(_r(f"skill:{s}", "pass") if ok else
                   _r(f"skill:{s}", "warn", f"install skill {s} under ~/.claude/skills"))
    for p in PLUGINS:
        ok = any(d.is_dir() for d in (home / ".claude/plugins/cache").glob(f"*/{p}"))
        out.append(_r(f"skill:{p}", "pass") if ok else
                   _r(f"skill:{p}", "warn", f"install the {p} plugin"))
    out.append(_r("atlassian-mcp", "warn", "check with /mcp"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kinetic.doctor")
    ap.add_argument("--repo", action="append", default=[], metavar="NAME=PATH")
    args = ap.parse_args(argv)
    repos = []
    for spec in args.repo:
        name, sep, path = spec.partition("=")
        if not sep or not name or not path:
            print(f"bad --repo {spec!r}: expected NAME=PATH", file=sys.stderr)
            return 2
        repos.append((name, path))
    res = checks(repos)
    ok = all(c["status"] != "fail" for c in res)
    print(json.dumps({"checks": res, "ok": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
