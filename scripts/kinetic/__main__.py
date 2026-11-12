from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

# scripts/kinetic/__main__.py -> parents[2] is the clone root.
ROOT = Path(__file__).resolve().parents[2]

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def clone_root() -> str:
    """Absolute path of the kinetic clone this package lives in."""
    return str(ROOT)


def _module_names() -> list:
    pkg = Path(__file__).resolve().parent
    return sorted(p.stem for p in pkg.glob("*.py")
                  if p.stem not in ("__init__", "__main__"))


def _usage() -> str:
    return ("usage: kinetic <module> [args...]\n"
            "       kinetic root\n"
            "       kinetic install --harness <h> [--uninstall]\n"
            "modules: " + " ".join(_module_names()))


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(_usage(), file=sys.stderr)
        return 2
    if args[0] in ("-h", "--help", "help"):
        print(_usage())
        return 0
    cmd, rest = args[0], args[1:]
    if cmd == "root":
        if rest:
            print("kinetic root takes no arguments", file=sys.stderr)
            return 2
        print(clone_root())
        return 0
    if not _NAME.fullmatch(cmd) or cmd not in _module_names():
        print(f"kinetic: unknown command '{cmd}'\n{_usage()}", file=sys.stderr)
        return 2
    mod = importlib.import_module(f"kinetic.{cmd}")
    fn = getattr(mod, "main", None)
    if fn is None:
        print(f"kinetic: module 'kinetic.{cmd}' has no main()", file=sys.stderr)
        return 2
    return fn(rest) or 0


if __name__ == "__main__":
    sys.exit(main())
