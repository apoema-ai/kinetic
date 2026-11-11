from __future__ import annotations

import json
import re
import sys

REQUIRED = ("## Threat model", "## Non-functional requirements", "## Acceptance criteria")
_TOP = re.compile(r"^#{1,2} ")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def lint(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    problems = []
    for heading in REQUIRED:
        idx = next((i for i, l in enumerate(lines) if l.rstrip() == heading), None)
        if idx is None:
            problems.append(f"missing section: {heading}")
            continue
        end = next((j for j in range(idx + 1, len(lines)) if _TOP.match(lines[j])), len(lines))
        if not _COMMENT.sub("", "\n".join(lines[idx + 1:end])).strip():
            problems.append(f"empty section: {heading}")
    return problems


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python3 -m kinetic.spec_lint <spec-file>", file=sys.stderr)
        return 2
    try:
        with open(args[0]) as fh:
            problems = lint(fh.read())
    except OSError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
