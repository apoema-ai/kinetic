from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CENTRAL = Path.home() / ".config/kinetic/repos.json"


class ConfigError(Exception):
    pass


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def resolve(repo_name: str, repo_path: Path, central: Path = DEFAULT_CENTRAL) -> dict:
    """Merge central per-repo config with <repo>/.kinetic.json (repo wins)."""
    repo_file = Path(repo_path) / ".kinetic.json"
    merged = {**_load(central).get(repo_name, {}), **_load(repo_file)}
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
