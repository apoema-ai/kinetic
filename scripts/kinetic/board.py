from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from kinetic import frontier, graph, state

HEADER_KEYS = ("Status", "Type", "Repo", "Slice", "Blocked by", "After", "Ships with",
               "Related", "Assignee")
# Assignee is derived from Type, so a hand edit of it is not drift
_DRIFT_KEYS = tuple(k for k in HEADER_KEYS if k != "Assignee")
_BOLD = re.compile(r"^\*\*([^*:]+):\*\*[ \t]*(.*)$")


def _list(items) -> str:
    items = list(items)
    return ", ".join(items) if items else "None"


def _values(t: dict) -> dict:
    kind = state.field(t, "kind")
    return {
        "Status": str(t.get("status") or "None"),
        "Type": str(kind),
        "Repo": str(t.get("repo") or "None"),
        "Slice": str(t.get("slice") or "None"),
        "Blocked by": _list(f"{e['id']} ({e['type']})" for e in t.get("blocked_by") or []),
        "After": _list(state.field(t, "after")),
        "Ships with": str(state.field(t, "ships_with") or "None"),
        "Related": _list(state.field(t, "related")),
        "Assignee": "you" if kind == "human" else "agent",
    }


def header_lines(t: dict) -> list[str]:
    v = _values(t)
    return [f"**{k}:** {v[k]}" for k in HEADER_KEYS]


def parse_header(text: str) -> dict[str, str]:
    """Bold-key lines after the optional title, up to the first line that is not one."""
    out: dict[str, str] = {}
    started = False
    for line in text.splitlines():
        m = _BOLD.match(line)
        if m:
            started = True
            out.setdefault(m.group(1).strip(), m.group(2).strip())
        elif started:
            break
        elif line.strip() and not line.startswith("# "):
            break
    return out


def _path(run_dir, ticket_id: str) -> Path:
    return Path(run_dir) / "issues" / f"{ticket_id}.md"


def _read(p: Path):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_strict(p: Path):
    """Strict UTF-8: the ticket body is the only copy, so never rewrite what cannot be decoded."""
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def write_header(run_dir, ticket_id: str) -> Path:
    t = state.load(run_dir)["tickets"].get(ticket_id)
    if t is None:
        raise KeyError(f"unknown ticket id: {ticket_id}")
    p = _path(run_dir, ticket_id)
    new = dict(zip(HEADER_KEYS, header_lines(t)))
    text = _read_strict(p)
    if text is None:
        lines = [f"# {ticket_id}"]
    else:
        lines = text.split("\n")
    title = 1 if lines and lines[0].startswith("# ") else 0
    start = title
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or not _BOLD.match(lines[start]):
        start = title  # no header block yet: insert right after the title
    end = start
    while end < len(lines) and _BOLD.match(lines[end]):
        end += 1
    seen, region = set(), []
    for line in lines[start:end]:
        key = _BOLD.match(line).group(1).strip()
        if key in new:
            if key not in seen:  # a duplicate owned line is dropped
                region.append(new[key])
            seen.add(key)
        else:
            region.append(line)
    missing = [new[k] for k in HEADER_KEYS if k not in seen]
    tail = lines[end:]
    if text is None:
        tail = [""]
    elif not region and not missing:
        pass
    elif tail and tail[0].strip() and not _BOLD.match(tail[0]) and not region:
        tail = [""] + tail  # keep inserted header apart from body text
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines[:start] + missing + region + tail))
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return p


def _title(run_dir, ticket_id: str) -> str:
    text = _read(_path(run_dir, ticket_id)) or ""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ticket_id


def _order(tickets: dict) -> list[str]:
    try:
        return graph.topo_order(tickets)
    except ValueError:
        return sorted(tickets)  # hard cycle: graph validate reports it


def render(run_dir) -> Path:
    st = state.load(run_dir)
    tickets = st["tickets"]
    waiting = frontier.waiting_on_you(st)
    rest = [i for i in _order(tickets) if i not in waiting]

    def row(i):
        t, v = tickets[i], _values(tickets[i])
        title = _title(run_dir, i).replace("|", "\\|")
        blocked = _list(e["id"] for e in t.get("blocked_by") or [])
        return f"| {i} | {title} | {v['Type']} | {v['Status']} | {blocked} | {v['After']} |"

    head = ["| id | title | type | status | blocked by | after |", "|---|---|---|---|---|---|"]
    out = ["# Board", ""]
    if waiting:
        out += ["## Waiting on you", ""] + head + [row(i) for i in waiting] + [""]
    out += ["## Tickets", ""] + head + [row(i) for i in rest] + [""]
    p = Path(run_dir) / "issues" / "README.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out), encoding="utf-8")
    return p


def drift(run_dir) -> list[dict]:
    tickets = state.load(run_dir)["tickets"]
    out = []
    for i in _order(tickets):
        want = _values(tickets[i])
        text = _read(_path(run_dir, i))
        have = parse_header(text) if text is not None else {}
        for k in _DRIFT_KEYS:
            # a key absent from an existing file (0.2.0 or hand-written) is not drift
            if text is not None and k not in have:
                continue
            if have.get(k) != want[k]:
                out.append({"id": i, "key": k, "file": have.get(k), "state": want[k]})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kinetic.board")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("render", "header", "drift"):
        s = sub.add_parser(name)
        s.add_argument("--run", required=True)
        if name == "header":
            s.add_argument("--id", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "render":
            res = {"path": str(render(a.run))}
        elif a.cmd == "header":
            res = {"path": str(write_header(a.run, a.id))}
        else:
            res = {"drift": drift(a.run)}
    except (KeyError, ValueError, OSError) as e:
        print(e.args[0] if isinstance(e, KeyError) and e.args else str(e), file=sys.stderr)
        return 1
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
