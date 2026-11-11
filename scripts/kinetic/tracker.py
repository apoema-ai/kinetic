from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from kinetic.config import ConfigError, _load

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = Path.home() / ".config/kinetic/settings.json"

TRACKERS = ("jira", "github", "linear", "local", "other")
ROLES = (
    "kind.agent", "kind.human",
    "edge.snapshot", "edge.merge", "edge.release",
    "after", "ships_with", "related",
    "status.todo", "status.running", "status.done", "status.merged", "status.blocked",
)
REQUIRED = {
    "jira": ["jira_project", "slice_issue_type", "child_issue_type"],
    "github": ["github_repo"],
    "linear": ["linear_team"],
    "local": [],
    "other": [],
}
_LEGACY = ("jira_project", "slice_issue_type", "child_issue_type")
_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.S)


class TrackerError(Exception):
    pass


def _get(d: dict, dotted: str):
    for part in dotted.split("."):
        if not isinstance(d, dict) or part not in d:
            raise KeyError(dotted)
        d = d[part]
    return d


def adapter_defaults(path: Path) -> dict:
    m = _BLOCK.search(Path(path).read_text())
    if not m:
        raise TrackerError(f"no json block in adapter {path}")
    try:
        d = json.loads(m.group(1))
    except ValueError as e:
        raise TrackerError(f"invalid json block in adapter {path}: {e}")
    for role in ROLES:
        try:
            _get(d, role)
        except KeyError:
            raise TrackerError(f"adapter {path} lacks role '{role}'")
    return d


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _settings(path: Path) -> dict:
    try:
        return _load(Path(path))
    except ConfigError as e:
        raise TrackerError(str(e))


def resolve(settings: Path = DEFAULT_SETTINGS, plugin_root: Path = ROOT) -> dict:
    cfg = _settings(settings)
    tracker = cfg.get("tracker") or "local"
    if tracker not in TRACKERS:
        raise TrackerError(f"unknown tracker '{tracker}': expected one of {', '.join(TRACKERS)}")
    ts = {k: cfg[k] for k in _LEGACY if cfg.get(k)}
    ts.update(cfg.get("tracker_settings") or {})
    missing = [k for k in REQUIRED[tracker] if not ts.get(k)]
    if missing:
        raise TrackerError(f"tracker '{tracker}' needs setting(s): {', '.join(missing)}")
    description = cfg.get("tracker_description") or None
    if tracker == "other" and not description:
        raise TrackerError("tracker 'other' needs tracker_description in settings")
    adapter = Path(plugin_root) / "trackers" / f"{tracker}.md"
    names = _merge(adapter_defaults(adapter), cfg.get("tracker_names") or {})
    return {
        "tracker": tracker,
        "adapter": str(adapter),
        "settings": ts,
        "names": names,
        "description": description if tracker in ("local", "other") else None,
    }


def pr_template(repo_path: Path | None, settings: Path = DEFAULT_SETTINGS,
                plugin_root: Path = ROOT) -> str:
    """First of: repo .kinetic.json, settings.json, plugin default. Relative paths resolve
    against the directory of the config file that set them."""
    sources = []
    if repo_path is not None:
        repo_file = Path(repo_path) / ".kinetic.json"
        sources.append((repo_file, _settings(repo_file)))
    sources.append((Path(settings), _settings(settings)))
    for cfg_file, cfg in sources:
        value = cfg.get("pr_template")
        if value:
            p = Path(value)
            if not p.is_absolute():
                p = cfg_file.parent / p
            if not p.is_file():
                raise TrackerError(f"pr_template file not found: {p} (set in {cfg_file})")
            return str(p)
    return str(Path(plugin_root) / "templates" / "pr-body.md")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kinetic.tracker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("resolve")
    p = sub.add_parser("pr-template")
    p.add_argument("--repo")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "resolve":
            out = resolve()
        else:
            out = {"path": pr_template(Path(a.repo) if a.repo else None)}
    except TrackerError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
