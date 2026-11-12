from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from kinetic import config, harness, tracker

SKILLS = ["find-ticket-repos", "checkout-ticket-repos", "resolving-merge-conflicts"]
PLUGINS = ["superpowers", "dev-fleet"]
GH_TIMEOUT = 10


def _r(name: str, status: str, fix: str = "") -> dict:
    return {"name": name, "status": status, "fix": fix}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expand(spec: str, home: Path) -> Path:
    """Expand a harness dir spec ('~/...' or a plain path) against home."""
    if spec == "~":
        return home
    if spec.startswith("~/"):
        return home / spec[2:]
    return Path(spec)


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


def _resolve_harness(harness_id, settings: Path):
    """(harness id, profile, error). On error the claude profile is returned so
    companion checks keep their pre-harness behaviour."""
    try:
        hid = harness.active_harness(harness=harness_id, settings=settings)
        return hid, harness.profile(hid), None
    except harness.HarnessError as e:
        return harness.DEFAULT_HARNESS, harness.profile(harness.DEFAULT_HARNESS), str(e)


def _harness_check(cfg: dict, hid: str, settings: Path) -> dict:
    """settings.json records the harness and clone the installer wrote."""
    recorded = cfg.get("harness")
    clone = cfg.get("clone")
    install = f"kinetic install --harness {hid}"
    if recorded and recorded != hid:
        return _r("harness", "warn",
                  f"settings records harness '{recorded}', not '{hid}'; "
                  f"run: {install}")
    if recorded == hid and isinstance(clone, str) and clone:
        return _r("harness", "pass")
    if recorded == hid:
        return _r("harness", "warn",
                  f"harness recorded but clone is not in {settings}; run: {install}")
    # warn, not fail: a dev checkout or a not-yet-installed setup is expected
    # to have no install record (same as missing central-config or skills).
    return _r("harness", "warn", f"harness not recorded in {settings}; run: {install}")


def _manifest_path(home: Path, hid: str) -> Path:
    return home / ".config" / "kinetic" / f"install-manifest-{hid}.json"


def _read_manifest(path: Path):
    """The manifest dict, or None when missing, unreadable or not an object."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _stale_files(manifest: dict) -> list[str]:
    """Manifest-listed paths whose current content no longer matches."""
    stale = []
    for name, meta in sorted((manifest.get("files") or {}).items()):
        if not isinstance(meta, dict):
            stale.append(name)
            continue
        path = Path(name)
        want = meta.get("sha256")
        if meta.get("type") == "symlink":
            fresh = False
            if os.path.islink(path):
                try:
                    target = os.readlink(path)
                except OSError:
                    target = None
                fresh = (target is not None
                         and target == meta.get("target")
                         and (not want or _sha256(target.encode()) == want))
        else:
            fresh = False
            if path.is_file() and not path.is_symlink():
                try:
                    fresh = not want or _sha256(path.read_bytes()) == want
                except OSError:
                    fresh = False
        if not fresh:
            stale.append(name)
    return stale


def _hooks_checks(clone, hid: str) -> list[dict]:
    """hooks.json must exist in the recorded clone. On Codex, hook trust is a
    separate stub check until the Codex installer lands."""
    install = f"kinetic install --harness {hid}"
    if not clone:
        return [_r("hooks-registered", "warn", f"no clone recorded; run: {install}")]
    cpath = Path(clone)
    if not cpath.is_dir():
        return [_r("hooks-registered", "fail",
                   f"clone path missing: {clone}; re-run: {install}")]
    hooks_json = cpath / "hooks" / "hooks.json"
    if not hooks_json.is_file():
        return [_r("hooks-registered", "fail",
                   f"{hooks_json} missing in clone; re-run: {install}")]
    out = [_r("hooks-registered", "pass")]
    if hid == "codex":
        # Stub: hooks.json exists in the clone, but Codex hook trust (/hooks)
        # cannot be verified programmatically yet — the Codex ticket refines.
        out.append(_r("hooks-trusted", "warn",
                      "run /hooks and trust kinetic's hooks"))
    return out


def _tier_check(hid: str, settings: Path) -> dict:
    try:
        for tier in harness.TIERS:
            harness.resolve_tier(hid, tier, settings=settings)
    except harness.HarnessError as e:
        return _r("tier-mapping", "fail", f"{e}; fix 'tiers' in {settings}")
    return _r("tier-mapping", "pass")


def _install_checks(home: Path, hid: str, settings: Path, cfg: dict) -> list[dict]:
    install = f"kinetic install --harness {hid}"
    out = []
    mpath = _manifest_path(home, hid)
    manifest = _read_manifest(mpath)
    if manifest is None:
        if mpath.is_file():
            out.append(_r("install-manifest", "fail",
                          f"unreadable manifest {mpath}; re-run: {install}"))
        else:
            out.append(_r("install-manifest", "warn",
                          f"no install manifest for harness {hid}; run: {install}"))
    else:
        stale = _stale_files(manifest)
        if stale:
            out.append(_r("install-manifest", "fail",
                          f"{len(stale)} generated file(s) stale or missing; "
                          f"re-run: {install}"))
        else:
            out.append(_r("install-manifest", "pass"))

    # settings "clone" belongs to the recorded harness's install; with a
    # --harness override it must not feed this harness's checks.
    clone = cfg.get("clone") if cfg.get("harness") in (None, hid) else None
    if not (isinstance(clone, str) and clone) and manifest:
        mc = manifest.get("clone")
        clone = mc if isinstance(mc, str) and mc else None
    out.extend(_hooks_checks(clone, hid))
    out.append(_tier_check(hid, settings))
    return out


def _skill_checks(home: Path, prof: dict) -> list[dict]:
    dirs = [_expand(d, home) for d in prof["skill_dirs"]]
    where = " or ".join(prof["skill_dirs"])
    out = []
    for s in SKILLS:
        ok = any((d / s / "SKILL.md").is_file() for d in dirs)
        out.append(_r(f"skill:{s}", "pass") if ok else
                   _r(f"skill:{s}", "warn", f"install skill {s} under {where}"))
    if prof["plugin_companions"]:
        # ~/.claude/plugins/cache is the only plugin cache location known
        # today; harnesses whose profile allows plugin companions are checked
        # there until per-harness installers land (Devin reads .claude-plugin).
        cache = home / ".claude/plugins/cache"
        for p in PLUGINS:
            ok = any(d.is_dir() for d in cache.glob(f"*/{p}"))
            out.append(_r(f"skill:{p}", "pass") if ok else
                       _r(f"skill:{p}", "warn", f"install the {p} plugin"))
    else:
        for p in PLUGINS:
            out.append(_r(f"skill:{p}", "na", "n/a, fallback used"))
    return out


def checks(repos: list[tuple[str, str]], home: Path | None = None,
           central: Path | None = None, settings: Path | None = None,
           harness_id: str | None = None) -> list[dict]:
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

    hid, prof, h_err = _resolve_harness(harness_id, settings)
    if h_err:
        out.append(_r("harness", "fail", h_err))
    else:
        try:
            cfg = config._load(settings)
        except config.ConfigError:
            cfg = {}
        out.append(_harness_check(cfg, hid, settings))
        out.extend(_install_checks(home, hid, settings, cfg))

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
    out.extend(_skill_checks(home, prof))
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


def _guarantees(prof: dict) -> list[dict]:
    """The Enforced/Instructed table for the active harness."""
    enforced = set(prof["enforced"])
    return [{"name": g, "level": "enforced" if g in enforced else "instructed"}
            for g in harness.GUARANTEES]


def _observability(settings: Path, home: Path, harness_id) -> dict:
    """Harness, clone path, tier mapping and the Enforced/Instructed table."""
    try:
        hid = harness.active_harness(harness=harness_id, settings=settings)
    except harness.HarnessError:
        return {}
    prof = harness.profile(hid)
    out = {"harness": hid, "guarantees": _guarantees(prof)}
    try:
        cfg = config._load(settings)
    except config.ConfigError:
        cfg = {}
    clone = cfg.get("clone") if cfg.get("harness") in (None, hid) else None
    if not (isinstance(clone, str) and clone):
        manifest = _read_manifest(_manifest_path(home, hid))
        mc = (manifest or {}).get("clone")
        clone = mc if isinstance(mc, str) and mc else None
    if clone:
        out["clone"] = clone
    try:
        out["tiers"] = {t: harness.resolve_tier(hid, t, settings=settings)
                        for t in harness.TIERS}
    except harness.HarnessError:
        pass  # the tier-mapping check already reports the failure
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kinetic.doctor")
    ap.add_argument("--repo", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--harness", choices=harness.HARNESS_IDS, default=None,
                    help="harness id; default: settings.json 'harness' or claude")
    args = ap.parse_args(argv)
    repos = []
    for spec in args.repo:
        name, sep, path = spec.partition("=")
        if not sep or not name or not path:
            print(f"bad --repo {spec!r}: expected NAME=PATH", file=sys.stderr)
            return 2
        repos.append((name, path))
    settings = tracker.DEFAULT_SETTINGS
    home = Path.home()
    res = checks(repos, home=home, settings=settings, harness_id=args.harness)
    ok = all(c["status"] != "fail" for c in res)
    payload = {"checks": res, "ok": ok}
    payload.update(_observability(settings, home, args.harness))
    print(json.dumps(payload))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
