"""Deterministic helpers for the repo catalog: the catalog_dir setting, reading
and writing catalog files, merging an approved change file, the index and lint.
The judgment (what a deliverable teaches) lives in skills/catalog-refresh."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from kinetic import config
from kinetic.discover import _real, _write

SETTINGS = Path.home() / ".config/kinetic/settings.json"
LAYOUT = ("index.md", "terms.md", "repos", "recipes", "ledger.json")


class CatalogError(ValueError):
    pass


# --- documents: Markdown with a JSON frontmatter block -----------------------

def read_doc(p: Path) -> tuple:
    p = Path(p)
    lines = p.read_text().split("\n")
    if not lines or lines[0].strip() != "---":
        raise CatalogError(f"{p}:1: missing opening '---'")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise CatalogError(f"{p}:1: missing closing '---'")
    try:
        meta = json.loads("\n".join(lines[1:end]))
    except ValueError as e:
        line = 1 + getattr(e, "lineno", 1)
        raise CatalogError(f"{p}:{line}: bad frontmatter JSON: {e}")
    if not isinstance(meta, dict):
        raise CatalogError(f"{p}:2: frontmatter must be a JSON object")
    return meta, "\n".join(lines[end + 1:])


def write_doc(p: Path, meta: dict, body: str) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("---\n" + json.dumps(meta, indent=2) + "\n---\n" + body)
    os.replace(tmp, p)


def render_terms(terms: dict) -> str:
    out = ["# Terms", "", "| Term | Meaning | Synonyms | Avoid |", "|---|---|---|---|"]
    for t in sorted(terms):
        e = terms[t]
        out.append(f"| {t} | {e.get('meaning', '')} | {', '.join(e.get('synonyms', []))} "
                   f"| {', '.join(e.get('avoid', []))} |")
    return "\n".join(out) + "\n"


def render_index(cat: dict) -> str:
    return "# Catalog index\n\n## Recipes\n\n## Repos\n"


# --- setting -----------------------------------------------------------------

def show(path=None):
    data = config._load(Path(path or SETTINGS))
    v = data.get("catalog_dir")
    return v if isinstance(v, str) and v else None


def is_catalog(d: str) -> bool:
    return os.path.isfile(os.path.join(d, "index.md")) and os.path.isdir(os.path.join(d, "recipes"))


def init_layout(d: Path) -> list:
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    created = []
    for name in LAYOUT:
        p = d / name
        if p.exists():
            continue
        if name in ("repos", "recipes"):
            p.mkdir()
        elif name == "ledger.json":
            _write(p, {})
        elif name == "terms.md":
            write_doc(p, {"terms": {}}, render_terms({}))
        else:
            p.write_text(render_index({}))
        created.append(name)
    return created


def set_dir(d: str, create: bool = False, path=None) -> dict:
    path = Path(path or SETTINGS)
    data = config._load(path)  # raises on bad JSON before anything is written
    real = _real(d)
    if not os.path.isdir(real) and not create:
        raise ValueError(f"not a directory: {d}")
    created = init_layout(Path(real)) if create else []
    data["catalog_dir"] = real
    _write(path, data)
    return {"catalog_dir": real, "created": created}


def _toplevel(cwd: str):
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
    except OSError:
        return None
    return _real(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def detect(cwd: str, path=None) -> dict:
    saved = show(path)
    candidates = []
    if saved:
        candidates.append({"path": saved, "reason": "saved"})
    cur = _real(cwd)
    top = _toplevel(cur) or cur
    while True:
        if is_catalog(cur) and cur != saved:
            candidates.append({"path": cur, "reason": "catalog at or above the current folder"})
            break
        if cur == top or os.path.dirname(cur) == cur:
            break
        cur = os.path.dirname(cur)
    return {"existing_config": saved, "candidates": candidates,
            "recommendation": candidates[0]["path"] if candidates else None}


# --- CLI ---------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.catalog")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("detect")
    sp.add_argument("--cwd", default=os.getcwd())
    sp = sub.add_parser("set")
    sp.add_argument("--dir", required=True)
    sp.add_argument("--create", action="store_true")
    sub.add_parser("show")
    a = p.parse_args(argv)
    try:
        if a.cmd == "detect":
            out = detect(a.cwd, SETTINGS)
        elif a.cmd == "set":
            out = set_dir(a.dir, a.create, SETTINGS)
        else:
            out = show(SETTINGS)
            print(json.dumps(out))
            return 0 if out else 1
    except (ValueError, OSError, config.ConfigError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
