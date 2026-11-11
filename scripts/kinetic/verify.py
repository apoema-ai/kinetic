from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kinetic import config, state


def run(run_dir, ticket_id, repo_name: str, repo_path, central=None) -> dict:
    """Run the repo's verify command, log combined output, record result in state."""
    repo_path = Path(repo_path)
    cfg = config.resolve(repo_name, repo_path, Path(central) if central else config.DEFAULT_CENTRAL)
    if not repo_path.is_dir():
        raise OSError(f"repo path is not a directory: {repo_path}")
    logs = Path(run_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    ts = started.strftime("%Y%m%dT%H%M%S%fZ")
    log_path = logs / f"verify-{ticket_id or repo_name}-{ts}.log"
    with open(log_path, "wb") as log:
        proc = subprocess.run(cfg["verify"], shell=True, cwd=str(repo_path),
                              stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    state.record_verify(run_dir, ticket_id, proc.returncode, str(log_path), repo_name,
                         at=started.isoformat(timespec="microseconds"))
    return {"exit_code": proc.returncode, "log_path": str(log_path)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.verify")
    p.add_argument("--run", required=True)
    p.add_argument("--repo-name", required=True)
    p.add_argument("--repo-path", required=True)
    p.add_argument("--ticket", default=None)
    a = p.parse_args(argv)
    try:
        res = run(Path(a.run), a.ticket, a.repo_name, Path(a.repo_path))
    except (config.ConfigError, OSError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(res))
    return res["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
