from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CENTRAL = Path.home() / ".config/kinetic/repos.json"


class ConfigError(Exception):
    pass


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        raise ConfigError(f"invalid JSON in {path}: {e}")
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return data


def resolve(repo_name: str, repo_path: Path, central: Path = DEFAULT_CENTRAL) -> dict:
    """Merge central per-repo config with <repo>/.kinetic.json (repo wins)."""
    repo_file = Path(repo_path) / ".kinetic.json"
    entry = _load(central).get(repo_name, {})
    if not isinstance(entry, dict):
        raise ConfigError(f"entry for repo '{repo_name}' in {central} must be a JSON object")
    merged = {**entry, **_load(repo_file)}
    if not merged.get("verify"):
        raise ConfigError(
            f"no verify command for repo '{repo_name}': set it in {central} or {repo_file}"
        )
    return {
        "verify": merged["verify"],
        "publish_snapshot": merged.get("publish_snapshot"),
        "pin": merged.get("pin"),
        "base_branch": merged.get("base_branch", "main"),
    }
