from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from kinetic import config, tracker

SKILLS = ["find-ticket-repos", "checkout-ticket-repos", "resolving-merge-conflicts"]
PLUGINS = ["superpowers", "dev-fleet"]
GH_TIMEOUT = 10


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
           central: Path | None = None, settings: Path | None = None) -> list[dict]:
    settings = Path(settings) if settings else tracker.DEFAULT_SETTINGS
    home = Path(home) if home else Path.home()
    central = Path(central) if central else config.DEFAULT_CENTRAL
    out = []
    gh_auth = None
    for tool in ("git", "gh"):
        found = shutil.which(tool)
        out.append(_r(tool, "pass") if found else _r(tool, "fail", f"install {tool} and put it on PATH"))
    if shutil.which("gh"):
        try:
            code = subprocess.run(["gh", "auth", "status", "--hostname", "github.com"],
                                  capture_output=True, timeout=GH_TIMEOUT).returncode
            fix = "run: gh auth login"
        except subprocess.TimeoutExpired:
            code, fix = 1, f"gh auth status timed out after {GH_TIMEOUT}s"
        except OSError as e:
            code, fix = 1, f"could not run gh auth status: {e}"
        gh_auth = _r("gh-auth", "pass") if code == 0 else _r("gh-auth", "fail", fix)
        out.append(gh_auth)
    central_res = _central_check(central)
    out.append(central_res)
    for name, path in repos:
        if central_res["status"] == "fail":
            out.append(_r(f"verify:{name}", "fail", "fix central-config first"))
            continue
        if not Path(path).is_dir():
            out.append(_r(f"verify:{name}", "fail", f"repo path not found: {path}"))
            continue
        try:
            config.resolve(name, Path(path), central)
            out.append(_r(f"verify:{name}", "pass"))
        except (config.ConfigError, OSError) as e:
            out.append(_r(f"verify:{name}", "fail", str(e)))
    for s in SKILLS:
        ok = (home / ".claude/skills" / s / "SKILL.md").is_file()
        out.append(_r(f"skill:{s}", "pass") if ok else
                   _r(f"skill:{s}", "warn", f"install skill {s} under ~/.claude/skills"))
    for p in PLUGINS:
        ok = any(d.is_dir() for d in (home / ".claude/plugins/cache").glob(f"*/{p}"))
        out.append(_r(f"skill:{p}", "pass") if ok else
                   _r(f"skill:{p}", "warn", f"install the {p} plugin"))
    out.extend(_tracker_checks(settings, gh_auth))
    return out


def _tracker_checks(settings: Path, gh_auth: dict | None) -> list[dict]:
    try:
        kind = tracker.resolve(settings=settings)["tracker"]
    except tracker.TrackerError as e:
        out = [_r("tracker", "fail", str(e)), _r("tracker-access", "fail", "fix tracker settings first")]
    else:
        if kind == "github":
            access = _r("tracker-access", gh_auth["status"], gh_auth["fix"]) if gh_auth else \
                _r("tracker-access", "fail", "run: gh auth login")
        elif kind in ("jira", "linear"):
            access = _r("tracker-access", "warn", "check the MCP with /mcp")
        else:
            access = _r("tracker-access", "pass")
        out = [_r("tracker", "pass"), access]
        if kind == "jira":
            out.append(_r("atlassian-mcp", "warn", "check with /mcp"))
    try:
        tracker.pr_template(None, settings=settings)
        out.append(_r("pr-template", "pass"))
    except tracker.TrackerError as e:
        out.append(_r("pr-template", "fail", str(e)))
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
