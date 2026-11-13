from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from kinetic import bare

# First match wins, in this order.
MARKERS = (
    ("pom.xml", "mvn -q verify"),
    ("build.gradle", "./gradlew check"),
    ("build.gradle.kts", "./gradlew check"),
    ("package.json", "npm test"),
    ("go.mod", "go test ./..."),
    ("Cargo.toml", "cargo test"),
    ("pyproject.toml", "python3 -m pytest"),
)


def _has_test_target(text: str) -> bool:
    return any(line.startswith("test:") for line in text.splitlines())


def _bare_ref(clone: Path) -> str:
    branch = bare.default_branch(clone)
    if branch:
        ref = f"origin/{branch}"
        r = subprocess.run(["git", "-C", str(clone), "rev-parse", "--verify", "--quiet",
                            f"{ref}^{{commit}}"], capture_output=True, text=True)
        if r.returncode == 0:
            return ref
    return "HEAD"


def _propose_bare(clone: Path) -> dict:
    ref = _bare_ref(clone)
    ls = subprocess.run(["git", "-C", str(clone), "ls-tree", "--name-only", ref],
                        capture_output=True, text=True)
    files = set(ls.stdout.splitlines()) if ls.returncode == 0 else set()
    for marker, cmd in MARKERS:
        if marker in files:
            return {"verify": cmd, "marker": marker}
    if "Makefile" in files:
        show = subprocess.run(["git", "-C", str(clone), "show", f"{ref}:Makefile"],
                              capture_output=True, text=True, errors="replace")
        if show.returncode == 0 and _has_test_target(show.stdout):
            return {"verify": "make test", "marker": "Makefile"}
    return {"verify": None, "marker": None}


def propose(repo_path) -> dict:
    repo_path = Path(repo_path)
    if bare.is_bare(repo_path):
        return _propose_bare(repo_path)
    for marker, cmd in MARKERS:
        if (repo_path / marker).is_file():
            return {"verify": cmd, "marker": marker}
    mk = repo_path / "Makefile"
    if mk.is_file() and _has_test_target(mk.read_text(errors="replace")):
        return {"verify": "make test", "marker": "Makefile"}
    return {"verify": None, "marker": None}


def main(argv=None) -> int:
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print("usage: kinetic detect_repos PATH [PATH ...]", file=sys.stderr)
        return 2
    print(json.dumps({p: propose(p) for p in paths}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
