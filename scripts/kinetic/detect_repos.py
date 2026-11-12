from __future__ import annotations

import json
import sys
from pathlib import Path

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


def _has_test_target(makefile: Path) -> bool:
    return any(line.startswith("test:") for line in makefile.read_text(errors="replace").splitlines())


def propose(repo_path) -> dict:
    repo_path = Path(repo_path)
    for marker, cmd in MARKERS:
        if (repo_path / marker).is_file():
            return {"verify": cmd, "marker": marker}
    mk = repo_path / "Makefile"
    if mk.is_file() and _has_test_target(mk):
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
