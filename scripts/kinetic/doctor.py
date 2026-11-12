from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from kinetic import config, harness, install, tracker

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


def _hook_commands_in_config(cfg) -> set:
    """Every command string under the "hooks" key of a hook config object
    (Devin config.json or a Codex hooks.json — same shape)."""
    cmds = set()
    hooks = cfg.get("hooks") if isinstance(cfg, dict) else None
    if not isinstance(hooks, dict):
        return cmds
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for g in groups:
            ghooks = g.get("hooks") if isinstance(g, dict) else None
            if not isinstance(ghooks, list):
                continue
            for h in ghooks:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    cmds.add(h["command"])
    return cmds


def _codex_hooks_checks(home: Path, clone, install_cmd: str) -> list[dict]:
    """Codex hooks live in ~/.codex/hooks.json (same event/matcher-group
    shape as Claude's). Registration is checkable; trust is not a simple
    file flag — Codex records per-hook trusted_hash state in
    ~/.codex/config.toml [hooks.state] after the user reviews them via
    /hooks, so doctor recomputes the expected hashes and compares."""
    hooks_path = home / ".codex" / "hooks.json"
    config_path = home / ".codex" / "config.toml"
    if not clone:
        return [_r("hooks-registered", "warn",
                   f"no clone recorded; run: {install_cmd}")]
    cpath = Path(clone)
    if not cpath.is_dir():
        return [_r("hooks-registered", "fail",
                   f"clone path missing: {clone}; re-run: {install_cmd}")]
    if not hooks_path.is_file():
        return [_r("hooks-registered", "warn",
                   f"no Codex hooks.json at {hooks_path}; run: {install_cmd}")]
    try:
        cfg = json.loads(hooks_path.read_text())
    except (OSError, ValueError):
        cfg = None
    if not isinstance(cfg, dict):
        return [_r("hooks-registered", "fail",
                   f"{hooks_path} is not a JSON object; fix it or re-run: "
                   f"{install_cmd}")]
    have = _hook_commands_in_config(cfg)
    missing = [c for c in install.codex_hook_commands(cpath) if c not in have]
    out = []
    if missing:
        out.append(_r("hooks-registered", "fail",
                      f"{len(missing)} kinetic hook(s) missing or pointing at "
                      f"a stale clone in {hooks_path}; re-run: {install_cmd}"))
    else:
        out.append(_r("hooks-registered", "pass"))
    report = install.codex_trust_report(hooks_path, config_path)
    if report["entries"] == 0:
        out.append(_r("hooks-trusted", "warn",
                      "no kinetic hook entries found to verify; run /hooks "
                      "in Codex and trust kinetic's hooks"))
    elif report["untrusted"]:
        out.append(_r("hooks-trusted", "fail",
                      f"{len(report['untrusted'])} of {report['entries']} "
                      "kinetic hook(s) not trusted or disabled; open Codex "
                      "and run /hooks to trust them"))
    else:
        out.append(_r("hooks-trusted", "pass",
                      f"all {report['entries']} kinetic hooks trusted"))
    return out


def _devin_hooks_checks(home: Path, clone, install_cmd: str) -> list[dict]:
    """Devin hooks live in ~/.config/devin/config.json, written by the
    installer in Devin's format (--harness devin, Devin tool matchers). The
    clone's hooks/hooks.json is Claude-format and must not be checked here."""
    cfg_path = home / ".config" / "devin" / "config.json"
    if not clone:
        return [_r("hooks-registered", "warn",
                   f"no clone recorded; run: {install_cmd}")]
    cpath = Path(clone)
    if not cpath.is_dir():
        return [_r("hooks-registered", "fail",
                   f"clone path missing: {clone}; re-run: {install_cmd}")]
    if not cfg_path.is_file():
        return [_r("hooks-registered", "warn",
                   f"no Devin hook config at {cfg_path}; run: {install_cmd}")]
    try:
        cfg = json.loads(cfg_path.read_text())
    except (OSError, ValueError):
        cfg = None
    if not isinstance(cfg, dict):
        return [_r("hooks-registered", "fail",
                   f"{cfg_path} is not a JSON object; fix it or re-run: "
                   f"{install_cmd}")]
    have = _hook_commands_in_config(cfg)
    missing = [c for c in install.devin_hook_commands(cpath) if c not in have]
    out = []
    if missing:
        out.append(_r("hooks-registered", "fail",
                      f"{len(missing)} kinetic hook(s) missing or pointing at "
                      f"a stale clone in {cfg_path}; re-run: {install_cmd}"))
    else:
        out.append(_r("hooks-registered", "pass"))
    # Devin has no separate hook-trust step like Codex's /hooks; plugin hooks
    # are best-effort and fail open, so this stays a warning to verify with
    # /hooks inside a Devin session.
    out.append(_r("hooks-trusted", "warn",
                  "Devin plugin hooks are best-effort; confirm they loaded "
                  "with /hooks in a Devin session"))
    return out


def _opencode_hooks_checks(home: Path, clone, install_cmd: str) -> list[dict]:
    """OpenCode hooks are the generated plugin
    ~/.config/opencode/plugins/kinetic.ts — a file-drop plugin with no
    registration or trust step. Check it exists, that it still points at the
    recorded clone (a moved clone leaves a stale baked-in path) and that the
    clone's hooks directory is present."""
    plugin = home / ".config" / "opencode" / "plugins" / "kinetic.ts"
    if not clone:
        return [_r("hooks-registered", "warn",
                   f"no clone recorded; run: {install_cmd}")]
    cpath = Path(clone)
    if not cpath.is_dir():
        return [_r("hooks-registered", "fail",
                   f"clone path missing: {clone}; re-run: {install_cmd}")]
    if not plugin.is_file():
        return [_r("hooks-registered", "warn",
                   f"no kinetic OpenCode plugin at {plugin}; run: {install_cmd}")]
    try:
        text = plugin.read_text()
    except OSError:
        text = ""
    # the plugin bakes the clone path as a quoted JSON string literal
    if json.dumps(str(cpath)) not in text or not (cpath / "hooks").is_dir():
        return [_r("hooks-registered", "fail",
                   f"{plugin} is stale (clone moved or hooks missing); "
                   f"re-run: {install_cmd}")]
    return [_r("hooks-registered", "pass"),
            _r("hooks-trusted", "na",
               "n/a, OpenCode plugins load without a trust step")]


def _hooks_checks(home: Path, clone, hid: str) -> list[dict]:
    """hooks must be registered for the harness; on Codex they must also be
    trusted via /hooks (verified against config.toml hooks.state)."""
    install_cmd = f"kinetic install --harness {hid}"
    if hid == "devin":
        return _devin_hooks_checks(home, clone, install_cmd)
    if hid == "codex":
        return _codex_hooks_checks(home, clone, install_cmd)
    if hid == "opencode":
        return _opencode_hooks_checks(home, clone, install_cmd)
    if not clone:
        return [_r("hooks-registered", "warn",
                   f"no clone recorded; run: {install_cmd}")]
    cpath = Path(clone)
    if not cpath.is_dir():
        return [_r("hooks-registered", "fail",
                   f"clone path missing: {clone}; re-run: {install_cmd}")]
    hooks_json = cpath / "hooks" / "hooks.json"
    if not hooks_json.is_file():
        return [_r("hooks-registered", "fail",
                   f"{hooks_json} missing in clone; re-run: {install_cmd}")]
    return [_r("hooks-registered", "pass")]


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
    out.extend(_hooks_checks(home, clone, hid))
    out.append(_tier_check(hid, settings))
    return out


def _json_names(node, out):
    """Collect every "name" string value in a JSON tree."""
    if isinstance(node, dict):
        name = node.get("name")
        if isinstance(name, str):
            out.add(name)
        for v in node.values():
            _json_names(v, out)
    elif isinstance(node, list):
        for v in node:
            _json_names(v, out)


def _devin_plugin_installed(home: Path, name: str) -> bool:
    """Whether a plugin named `name` is installed for Devin CLI.

    Checks ~/.local/share/devin/cli/plugins: resolved/required names in
    lock.json (covers --local linked installs, which leave no cache copy)
    and plugin manifests under cache/ (fetched installs)."""
    store = home / ".local" / "share" / "devin" / "cli" / "plugins"
    lock = store / "lock.json"
    if lock.is_file():
        try:
            data = json.loads(lock.read_text())
        except (OSError, ValueError):
            data = None
        if data is not None:
            names = set()
            _json_names(data, names)
            if name in names:
                return True
    cache = store / "cache"
    if cache.is_dir():
        for pj in cache.rglob("plugin.json"):
            try:
                data = json.loads(pj.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("name") == name:
                return True
    return False


def _skill_checks(home: Path, prof: dict) -> list[dict]:
    dirs = [_expand(d, home) for d in prof["skill_dirs"]]
    where = " or ".join(prof["skill_dirs"])
    out = []
    for s in SKILLS:
        ok = any((d / s / "SKILL.md").is_file() for d in dirs)
        out.append(_r(f"skill:{s}", "pass") if ok else
                   _r(f"skill:{s}", "warn", f"install skill {s} under {where}"))
    store = prof.get("plugin_store")
    if store == "devin-plugins":
        for p in PLUGINS:
            ok = _devin_plugin_installed(home, p)
            out.append(_r(f"skill:{p}", "pass") if ok else
                       _r(f"skill:{p}", "warn",
                          f"install the {p} plugin: devin plugins install <source>"))
    elif prof["plugin_companions"]:
        # Claude's plugin cache; other plugin_companions harnesses get their
        # own store check via prof["plugin_store"] above.
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
