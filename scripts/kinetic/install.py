from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _install_claude(clone: Path, home: Path) -> int:
    launcher = clone / "bin" / "kinetic"
    link = _bin_dir(home) / "kinetic"
    manifest_path = _manifest_path(home, "claude")
    prev = _read_manifest(manifest_path) or {}
    prev_files = prev.get("files") or {}

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

    settings_path = _settings_path(home)
    existed = settings_path.is_file()
    try:
        cfg = _load(settings_path)
    except ConfigError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return 1
    # A re-install keeps the FIRST install's rollback point so --uninstall
    # still restores the pre-install state and re-runs converge byte-for-byte.
    prev_sent = prev.get("settings") or {}
    if prev_sent.get("writes"):
        previous = prev_sent.get("previous") or {
            k: None for k in SETTING_KEYS}
        existed = bool(prev_sent.get("existed", existed))
    else:
        previous = {k: (cfg[k] if k in cfg else None) for k in SETTING_KEYS}
    cfg["harness"] = "claude"
    cfg["clone"] = str(clone)
    atomic_write(settings_path,
                 json.dumps(cfg, indent=2, sort_keys=True) + "\n")

    manifest = {
        "version": MANIFEST_VERSION,
        "harness": "claude",
        "clone": str(clone),
        "files": {str(link): _link_entry(link, launcher)},
        "settings": {
            "path": str(settings_path),
            "existed": existed,
            "writes": {"harness": "claude", "clone": str(clone)},
            "previous": previous,
        },
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


def _uninstall(harness_id: str, home: Path) -> int:
    manifest_path = _manifest_path(home, harness_id)
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        print(f"kinetic install: nothing installed for harness {harness_id}")
        return 0

    warnings = []
    removed = []
    for name, meta in sorted((manifest.get("files") or {}).items()):
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
    print(f"kinetic install: --harness {a.harness} is not yet supported",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
