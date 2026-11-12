from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from kinetic import harness
from kinetic.config import ConfigError, _load
from kinetic.state import atomic_write

MANIFEST_VERSION = 1

# settings.json keys the installer owns. Values recorded per install so
# --uninstall can restore what was there before (None = key was absent).
SETTING_KEYS = ("harness", "clone")


def _clone_root() -> Path:
    # scripts/kinetic/install.py -> parents[2] is the clone root.
    return Path(__file__).resolve().parents[2]


def _config_dir(home: Path) -> Path:
    return home / ".config" / "kinetic"


def _settings_path(home: Path) -> Path:
    return _config_dir(home) / "settings.json"


def _manifest_path(home: Path, harness_id: str) -> Path:
    return _config_dir(home) / f"install-manifest-{harness_id}.json"


def _bin_dir(home: Path) -> Path:
    return home / ".local" / "bin"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_link(path: Path) -> str:
    return _sha256_bytes(os.readlink(path).encode())


def _hash_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_manifest(path: Path):
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _git_toplevel(path: Path):
    try:
        p = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return Path(p.stdout.strip())


def _check_clone(clone: Path) -> str | None:
    """None when clone is a git worktree root, else an error message."""
    top = _git_toplevel(clone)
    if top is None or os.path.realpath(top) != os.path.realpath(clone):
        return (f"kinetic install must run from a git clone: {clone} is not "
                f"the root of a git worktree")
    if not (clone / "bin" / "kinetic").is_file():
        return f"kinetic install: clone is missing its launcher {clone / 'bin' / 'kinetic'}"
    return None


def _link_entry(link: Path, target: Path):
    return {"type": "symlink", "target": str(target),
            "sha256": _sha256_bytes(str(target).encode())}


def _ensure_link(link: Path, launcher: Path, prev_files: dict) -> int:
    """Point link at launcher, replacing only files a previous install wrote.
    A link already aimed at this launcher is accepted even when another
    harness's manifest recorded it. Returns 0, or 1 after printing why a
    foreign file blocked the install."""
    if os.path.lexists(link):
        if link.is_symlink() and os.readlink(link) == str(launcher):
            pass  # already ours and correct
        elif str(link) in prev_files and (link.is_symlink() or link.is_file()):
            link.unlink()  # a file a previous kinetic install wrote
        else:
            print(f"kinetic install: refusing to overwrite existing {link} "
                  f"(not written by kinetic); remove it and re-run",
                  file=sys.stderr)
            return 1
    if not (link.is_symlink() and os.readlink(link) == str(launcher)):
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(launcher)
    return 0


def _write_install_settings(home: Path, clone: Path, hid: str, prev) -> tuple | None:
    """Record harness+clone in ~/.config/kinetic/settings.json.
    Returns (settings_path, existed, previous) or None after printing the
    ConfigError. A re-install keeps the FIRST install's rollback point."""
    settings_path = _settings_path(home)
    existed = settings_path.is_file()
    try:
        cfg = _load(settings_path)
    except ConfigError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return None
    prev_sent = prev.get("settings") or {}
    if prev_sent.get("writes"):
        previous = prev_sent.get("previous") or {
            k: None for k in SETTING_KEYS}
        existed = bool(prev_sent.get("existed", existed))
    else:
        previous = {k: (cfg[k] if k in cfg else None) for k in SETTING_KEYS}
    cfg["harness"] = hid
    cfg["clone"] = str(clone)
    atomic_write(settings_path,
                 json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    return settings_path, existed, previous


def _settings_manifest(settings_path: Path, hid: str, clone: Path,
                       existed: bool, previous: dict) -> dict:
    return {
        "path": str(settings_path),
        "existed": existed,
        "writes": {"harness": hid, "clone": str(clone)},
        "previous": previous,
    }


def _install_claude(clone: Path, home: Path) -> int:
    launcher = clone / "bin" / "kinetic"
    link = _bin_dir(home) / "kinetic"
    manifest_path = _manifest_path(home, "claude")
    prev = _read_manifest(manifest_path) or {}
    prev_files = prev.get("files") or {}

    if _ensure_link(link, launcher, prev_files) != 0:
        return 1
    res = _write_install_settings(home, clone, "claude", prev)
    if res is None:
        return 1
    settings_path, existed, previous = res

    manifest = {
        "version": MANIFEST_VERSION,
        "harness": "claude",
        "clone": str(clone),
        "files": {str(link): _link_entry(link, launcher)},
        "settings": _settings_manifest(settings_path, "claude", clone,
                                       existed, previous),
    }
    atomic_write(manifest_path,
                 json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("installed kinetic for harness claude")
    print(f"  launcher: {link} -> {launcher}")
    print(f"  settings: harness=claude clone={clone} in {settings_path}")
    print(f"  manifest: {manifest_path}")
    print()
    print("Claude Code: register the clone as a plugin (kinetic does not "
          "automate this):")
    print(f"  claude --plugin-dir {clone}")
    print()
    print("Make sure ~/.local/bin is on your PATH (it is on most macOS/Linux "
          "setups; add it to your shell profile if `kinetic` is not found), "
          "then re-run `kinetic install --harness claude` after `git pull` "
          "to pick up updates.")
    return 0


# ---------------------------------------------------------------------------
# Devin CLI
#
# `kinetic install --harness devin` registers the clone as a local Devin
# plugin (`devin plugins install --local <clone>`; Devin reads
# .claude-plugin/plugin.json and namespaces skills /kinetic:<name>). The
# clone's hooks/hooks.json is Claude-format with `--harness claude` baked in
# and Claude tool-name matchers, so the installer writes a Devin-format hook
# config (Devin tool names, `--harness devin`) into the "hooks" key of
# ~/.config/devin/config.json, preserving every foreign entry. Entries are
# marked by the `--harness devin` command flag so re-installs replace them
# and --uninstall removes exactly them.


def _devin_config_path(home: Path) -> Path:
    return home / ".config" / "devin" / "config.json"


def _plugin_name(clone: Path) -> str:
    """The plugin name Devin namespaces skills under (/<name>:<skill>), read
    from the clone's plugin manifest; 'kinetic' when none names it."""
    for rel in (".devin-plugin/plugin.json", ".claude-plugin/plugin.json",
                "plugin.json"):
        try:
            data = json.loads((clone / rel).read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("name"), str) \
                and data["name"]:
            return data["name"]
    return "kinetic"


def _devin_hook_spec() -> list:
    """(event, matcher, script) triples mirroring hooks/hooks.json but with
    Devin tool names taken from the harness profile."""
    tools = harness.profile("devin")["tools"]
    edit = "|".join(tools["edit"]) or "a^"  # matches nothing when empty
    shell = tools["shell"]
    write_ops = (f"^{shell}$"
                 "|mcp__.*atlassian.*(create|edit|Edit|update|transition|"
                 "[Cc]omment|executeWrite|executeDestructive).*"
                 "|mcp__.*github.*(create_pull_request|merge_pull_request|"
                 "update_pull_request|push_files|create_or_update_file|"
                 "create_branch|delete_file).*")
    return [
        ("PostToolUse", f"^({edit})$", "record_edit.py"),
        ("PostToolUse", f"^{shell}$", "claim_run.py"),
        ("Stop", "", "completion_gate.py"),
        ("PreToolUse", f"^({edit})$", "isolation.py"),
        ("PreToolUse", write_ops, "confirm_write_ops.py"),
        ("PreToolUse", "mcp__.*deploy.*|mcp__.*tekton.*trigger.*",
         "confirm_deploy.py"),
        ("SessionStart", "", "orient.py"),
    ]


def _devin_hook_groups(clone: Path) -> dict:
    """{event: [matcher group, ...]} in Devin's hook config format."""
    groups = {}
    for event, matcher, script in _devin_hook_spec():
        groups.setdefault(event, []).append({
            "matcher": matcher,
            "hooks": [{"type": "command",
                       "command": f'python3 "{clone}/hooks/{script}.py"'
                                  " --harness devin",
                       "timeout": 10}]})
    return groups


def devin_hook_commands(clone: Path) -> list:
    """The hook command strings the Devin installer writes into the Devin
    config; doctor compares these against what is actually registered."""
    return [h["command"]
            for groups in _devin_hook_groups(clone).values()
            for g in groups for h in g["hooks"]]


def _is_kinetic_devin_hook(hook) -> bool:
    return (isinstance(hook, dict)
            and "--harness devin" in str(hook.get("command") or ""))


def _strip_kinetic_devin_hooks(hooks: dict) -> dict:
    """hooks minus every kinetic (`--harness devin`) hook entry; groups left
    empty are dropped. Malformed event values and groups are preserved."""
    out = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept_groups = []
        for g in groups:
            ghooks = g.get("hooks") if isinstance(g, dict) else None
            if not isinstance(ghooks, list):
                kept_groups.append(g)
                continue
            kept = [h for h in ghooks if not _is_kinetic_devin_hook(h)]
            if kept:
                kept_groups.append({**g, "hooks": kept})
        if kept_groups:
            out[event] = kept_groups
        # an event left with no groups is dropped (equivalent to [])
    return out


def _merge_devin_config(cfg: dict, clone: Path) -> dict:
    """Return cfg with kinetic's Devin hooks merged into cfg["hooks"],
    replacing any previously generated entries. Raises ValueError when the
    existing "hooks" value is not an object."""
    hooks = cfg.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" in the Devin config must be a JSON object')
    merged = _strip_kinetic_devin_hooks(hooks)
    for event, new_groups in _devin_hook_groups(clone).items():
        existing = merged.get(event)
        if existing is None:
            merged[event] = list(new_groups)
        elif isinstance(existing, list):
            existing.extend(new_groups)
        # a non-list foreign value is preserved and ours skipped for that event
    cfg["hooks"] = merged
    return cfg


def _read_json_object(path: Path):
    """(data, existed): {} / False for a missing file; ValueError on
    unreadable, non-JSON or non-object content."""
    if not os.path.lexists(path):
        return {}, False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot parse {path}: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data, True


def _devin_plugins_install(exe: str, clone: Path, name: str) -> int:
    """`devin plugins install --local <clone>` with inherited stdio so the
    trust prompt reaches the user. An already-installed plugin is fine: a
    --local install is linked, so its content already tracks the clone."""
    rc = subprocess.run([exe, "plugins", "install", "--local",
                         str(clone)]).returncode
    if rc == 0:
        return 0
    lst = subprocess.run([exe, "plugins", "list"],
                         capture_output=True, text=True)
    if lst.returncode == 0 and name in lst.stdout.split():
        print(f"kinetic install: devin plugin '{name}' already installed "
              f"(linked to {clone}); continuing")
        return 0
    print("kinetic install: `devin plugins install --local` failed; run "
          f"`devin plugins install --local {clone}` manually to see why",
          file=sys.stderr)
    return 1


def _install_devin(clone: Path, home: Path) -> int:
    launcher = clone / "bin" / "kinetic"
    link = _bin_dir(home) / "kinetic"
    manifest_path = _manifest_path(home, "devin")
    prev = _read_manifest(manifest_path) or {}
    prev_files = prev.get("files") or {}
    name = _plugin_name(clone)
    devin_cfg_path = _devin_config_path(home)

    exe = shutil.which("devin")
    if exe is None:
        print("kinetic install: 'devin' CLI not found on PATH; install Devin "
              "CLI and run `devin auth login` first", file=sys.stderr)
        return 1

    # Preflight the merge targets so a bad config fails before anything is
    # written or devin is invoked.
    try:
        devin_cfg, devin_existed = _read_json_object(devin_cfg_path)
        merged_cfg = _merge_devin_config(dict(devin_cfg), clone)
    except ValueError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return 1
    # Like settings, keep the FIRST install's existed flag so --uninstall
    # still knows whether it created the file.
    prev_dconf = prev.get("devin_config") or {}
    if prev_dconf.get("path") == str(devin_cfg_path):
        devin_existed = bool(prev_dconf.get("existed", devin_existed))
    try:
        _load(_settings_path(home))
    except ConfigError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return 1

    # The plugin registration is the external step: run it before writing
    # any local state so a failure (not signed in, trust declined) leaves
    # nothing behind. Local --local plugins are linked, so a re-run after a
    # later failure is tolerated by the already-installed fallback.
    if _devin_plugins_install(exe, clone, name) != 0:
        return 1

    if _ensure_link(link, launcher, prev_files) != 0:
        return 1
    res = _write_install_settings(home, clone, "devin", prev)
    if res is None:
        return 1
    settings_path, existed, previous = res

    devin_cfg_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(devin_cfg_path,
                 json.dumps(merged_cfg, indent=2, sort_keys=True) + "\n")

    manifest = {
        "version": MANIFEST_VERSION,
        "harness": "devin",
        "clone": str(clone),
        "files": {str(link): _link_entry(link, launcher)},
        "settings": _settings_manifest(settings_path, "devin", clone,
                                       existed, previous),
        "devin_config": {"path": str(devin_cfg_path),
                         "existed": devin_existed},
        "plugin": {"name": name, "scope": "local"},
    }
    atomic_write(manifest_path,
                 json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("installed kinetic for harness devin")
    print(f"  launcher: {link} -> {launcher}")
    print(f"  plugin: devin plugins install --local {clone} "
          f"(skills as /{name}:<skill>)")
    print(f"  hooks: {devin_cfg_path} (Devin format, --harness devin)")
    print(f"  settings: harness=devin clone={clone} in {settings_path}")
    print(f"  manifest: {manifest_path}")
    print()
    print("Verify inside Devin: /hooks lists kinetic's hooks and "
          "/kinetic:<skill> resolves. See docs/smoke/devin.md for the "
          "support checklist.")
    print()
    print("Make sure ~/.local/bin is on your PATH (it is on most macOS/Linux "
          "setups; add it to your shell profile if `kinetic` is not found), "
          "then re-run `kinetic install --harness devin` after `git pull` "
          "to pick up updates (a --local plugin tracks the clone).")
    return 0


def _remove_listed(path: Path, meta: dict):
    """Remove one manifest-listed path. Returns a warning or None."""
    mtype = meta.get("type")
    want_hash = meta.get("sha256")
    if mtype == "symlink":
        if os.path.islink(path):
            if os.readlink(path) == meta.get("target") and \
                    _hash_link(path) == want_hash:
                path.unlink()
                return None
            return f"left {path}: symlink target changed since install"
        if os.path.lexists(path):
            return f"left {path}: no longer a symlink"
        return None
    if path.is_symlink() or not path.is_file():
        if os.path.lexists(path):
            return f"left {path}: unexpected file type"
        return None
    if want_hash and _hash_file(path) != want_hash:
        return f"left {path}: content changed since install"
    path.unlink()
    return None


def _other_manifest_files(home: Path, harness_id: str) -> set:
    """Paths other harnesses' manifests still claim as generated files, so
    this uninstall does not remove a launcher another install needs."""
    claimed = set()
    cfgdir = _config_dir(home)
    if not cfgdir.is_dir():
        return claimed
    for mp in cfgdir.glob("install-manifest-*.json"):
        if mp.name == f"install-manifest-{harness_id}.json":
            continue
        m = _read_manifest(mp)
        if m:
            claimed.update((m.get("files") or {}).keys())
    return claimed


def _strip_devin_config(path: Path, existed: bool):
    """Remove kinetic's `--harness devin` hooks from a Devin config.json,
    preserving everything else. Returns a warning or None."""
    if not path.is_file():
        return None
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return f"left {path}: {e}"
    if not isinstance(cfg, dict):
        return f"left {path}: not a JSON object"
    hooks = cfg.get("hooks")
    if isinstance(hooks, dict):
        stripped = _strip_kinetic_devin_hooks(hooks)
        if stripped:
            cfg["hooks"] = stripped
        else:
            cfg.pop("hooks", None)
    elif hooks is not None:
        return f"left {path}: 'hooks' is not an object; kinetic hooks may remain"
    if not cfg:
        if existed:
            atomic_write(path, "{}\n")
        else:
            path.unlink()
        return None
    atomic_write(path, json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    return None


def _uninstall(harness_id: str, home: Path) -> int:
    manifest_path = _manifest_path(home, harness_id)
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        print(f"kinetic install: nothing installed for harness {harness_id}")
        return 0

    warnings = []
    removed = []
    kept = []
    claimed = _other_manifest_files(home, harness_id)
    for name, meta in sorted((manifest.get("files") or {}).items()):
        if name in claimed:
            kept.append(f"{name} (also installed for another harness)")
            continue
        path = Path(name)
        warn = _remove_listed(path, meta)
        if warn:
            warnings.append(warn)
        else:
            removed.append(name)

    sent = manifest.get("settings") or {}
    sp = Path(sent["path"]) if sent.get("path") else None
    if sp is not None and sp.is_file():
        try:
            cfg = _load(sp)
        except ConfigError as e:
            cfg = None
            warnings.append(f"left {sp}: {e}")
        if cfg is not None:
            changed = False
            for key, written in (sent.get("writes") or {}).items():
                if cfg.get(key) == written:
                    prev = (sent.get("previous") or {}).get(key)
                    if prev is None:
                        cfg.pop(key, None)
                    else:
                        cfg[key] = prev
                    changed = True
                elif key in cfg:
                    warnings.append(
                        f"settings key '{key}' in {sp} changed since "
                        f"install; left as is")
            if changed:
                if not cfg and not sent.get("existed", True):
                    sp.unlink()
                    removed.append(str(sp))
                else:
                    atomic_write(sp, json.dumps(cfg, indent=2,
                                                sort_keys=True) + "\n")
                    removed.append(str(sp))

    dconf = manifest.get("devin_config")
    if isinstance(dconf, dict) and dconf.get("path"):
        dpath = Path(dconf["path"])
        warn = _strip_devin_config(dpath, bool(dconf.get("existed")))
        if warn:
            warnings.append(warn)
        elif dpath.exists():
            kept.append(str(dpath) + " (foreign entries kept)")

    plugin = manifest.get("plugin")
    pname = plugin.get("name") if isinstance(plugin, dict) else None
    if isinstance(pname, str) and pname:
        exe = shutil.which("devin")
        if exe is None:
            warnings.append(
                f"devin CLI not on PATH; remove the plugin manually: "
                f"devin plugins remove {pname} --local")
        else:
            rc = subprocess.run([exe, "plugins", "remove", pname,
                                 "--local"]).returncode
            if rc != 0:
                warnings.append(
                    f"`devin plugins remove {pname} --local` failed; "
                    "remove the plugin manually")

    manifest_path.unlink(missing_ok=True)
    removed.append(str(manifest_path))
    for d in (_config_dir(home), _bin_dir(home)):
        try:
            d.rmdir()
        except OSError:
            pass

    print(f"uninstalled kinetic for harness {harness_id}")
    for name in removed:
        print(f"  removed: {name}")
    for name in kept:
        print(f"  kept: {name}")
    for w in warnings:
        print(f"  warning: {w}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kinetic install")
    ap.add_argument("--harness", required=True, choices=harness.HARNESS_IDS,
                    help="harness to install for")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove everything the manifest lists")
    a = ap.parse_args(argv)

    home = Path.home()
    if a.uninstall:
        return _uninstall(a.harness, home)

    clone = _clone_root()
    err = _check_clone(clone)
    if err:
        print(f"kinetic install: {err}", file=sys.stderr)
        return 1
    if a.harness == "claude":
        return _install_claude(clone, home)
    if a.harness == "devin":
        return _install_devin(clone, home)
    print(f"kinetic install: --harness {a.harness} is not yet supported",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
