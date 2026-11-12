from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kinetic import state


def run(run_dir, ticket_id: str, repo_path, command: str) -> dict:
    """Run a test command in the ticket worktree and record it as RED evidence if it fails.

    A passing command is not RED (the test does not yet fail for the missing behaviour),
    so nothing is recorded and an earlier RED record is left alone."""
    repo_path = Path(repo_path)
    if not repo_path.is_dir():
        raise OSError(f"repo path is not a directory: {repo_path}")
    logs = Path(run_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    ts = started.strftime("%Y%m%dT%H%M%S%fZ")
    log_path = logs / f"{ticket_id}-red-{ts}.log"
    with open(log_path, "wb") as log:
        proc = subprocess.run(command, shell=True, cwd=str(repo_path),
                              stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    recorded = proc.returncode != 0
    if recorded:
        state.record_red(run_dir, ticket_id, proc.returncode, str(log_path), command,
                         at=started.isoformat(timespec="microseconds"))
    return {"exit_code": proc.returncode, "log_path": str(log_path), "recorded": recorded}


def main(argv=None) -> int:
    """Exit 0 when the command failed and was recorded as RED; 1 when it passed
    (not a RED, fix the test); 2 on a bad path. Note this inverts the command's own exit code."""
    p = argparse.ArgumentParser(prog="kinetic.red")
    p.add_argument("--run", required=True)
    p.add_argument("--ticket", required=True)
    p.add_argument("--repo-path", required=True)
    p.add_argument("--command", required=True, help="the focused test command, expected to fail")
    a = p.parse_args(argv)
    try:
        res = run(Path(a.run), a.ticket, Path(a.repo_path), a.command)
    except OSError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(res))
    if not res["recorded"]:
        print("not a RED: the command passed. Fix the test so it fails for the missing "
              "behaviour, then run kinetic red again.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
