from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from kinetic import board, state


def mk(tmp, tickets):
    run = Path(tmp)
    state.init(run, "epic", "x")
    for tid, f in tickets.items():
        state.set_ticket(run, tid, **f)
    (run / "issues").mkdir(exist_ok=True)
    return run


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = board.main(list(argv))
    return rc, out.getvalue(), err.getvalue()


AGENT = {"repo": "lib-x", "slice": "01-s", "blocked_by": [{"id": "02-svc-y", "type": "merge"}]}


class BoardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def test_header_roundtrip(self):
        t = {"repo": "lib-x", "slice": "01-s", "status": "todo", "kind": "human",
             "blocked_by": [{"id": "a", "type": "merge"}, {"id": "b", "type": "snapshot"}],
             "after": ["c", "d"], "ships_with": "grp", "related": ["e"]}
        parsed = board.parse_header("\n".join(board.header_lines(t)))
        self.assertEqual(list(parsed), list(board.HEADER_KEYS))
        self.assertEqual(parsed["Blocked by"], "a (merge), b (snapshot)")
        self.assertEqual(parsed["Assignee"], "you")
        self.assertEqual(parsed["Type"], "human")
        self.assertEqual(parsed["Ships with"], "grp")
        empty = board.parse_header("\n".join(board.header_lines({"status": "todo"})))
        self.assertEqual(empty["Repo"], "None")
        self.assertEqual(empty["After"], "None")
        self.assertEqual(empty["Assignee"], "agent")

    def test_write_header_keeps_body(self):
        run = mk(self.tmp, {"01-lib-x-a": AGENT, "02-svc-y": {"repo": "svc-y"}})
        p = run / "issues" / "01-lib-x-a.md"
        p.write_text("# 01: Title\n\n**Slice:** old\n**What to build:** x\n\n- [ ] one\n- [ ] two\n")
        self.assertEqual(board.write_header(run, "01-lib-x-a"), p)
        text = p.read_text()
        self.assertTrue(text.startswith("# 01: Title\n"))
        self.assertIn("**What to build:** x", text)
        self.assertIn("- [ ] one\n- [ ] two\n", text)
        self.assertNotIn("**Slice:** old", text)
        parsed = board.parse_header(text)
        self.assertEqual(parsed["Slice"], "01-s")
        self.assertEqual(parsed["Blocked by"], "02-svc-y (merge)")
        self.assertEqual(text.count("**Slice:**"), 1)
        self.assertEqual([d for d in board.drift(run) if d["id"] == "01-lib-x-a"], [])

    def test_write_header_creates_missing_file(self):
        run = mk(self.tmp, {"01-lib-x-a": AGENT, "02-svc-y": {"repo": "svc-y"}})
        p = board.write_header(run, "02-svc-y")
        self.assertTrue(p.read_text().startswith("# 02-svc-y\n"))
        self.assertEqual(board.parse_header(p.read_text())["Repo"], "svc-y")

    def test_render_waiting_first(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"},
                            "02-you": {"kind": "human"}})
        (run / "issues" / "01-lib-x-a.md").write_text("# 01: Build lib\n")
        p = board.render(run)
        self.assertEqual(p, run / "issues" / "README.md")
        text = p.read_text()
        self.assertIn("| id | title | type | status | blocked by | after |", text)
        self.assertLess(text.index("## Waiting on you"), text.index("01: Build lib"))
        self.assertLess(text.index("02-you"), text.index("01: Build lib"))

    def test_drift_reports_hand_edit(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x", "slice": "01-s"}})
        board.write_header(run, "01-lib-x-a")
        p = run / "issues" / "01-lib-x-a.md"
        p.write_text(p.read_text().replace("**Status:** todo", "**Status:** done"))
        self.assertEqual(board.drift(run), [{"id": "01-lib-x-a", "key": "Status",
                                             "file": "done", "state": "todo"}])

    def test_drift_malformed_value_does_not_raise(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"}})
        board.write_header(run, "01-lib-x-a")
        p = run / "issues" / "01-lib-x-a.md"
        p.write_text(p.read_text().replace("**Status:** todo", "**Status:** dnoe")
                     .replace("**Blocked by:** None", "**Blocked by:** ???"))
        d = {(x["key"], x["file"]) for x in board.drift(run)}
        self.assertEqual(d, {("Status", "dnoe"), ("Blocked by", "???")})

    def test_drift_none_when_in_sync(self):
        run = mk(self.tmp, {"01-lib-x-a": AGENT, "02-svc-y": {"kind": "human"}})
        for tid in ("01-lib-x-a", "02-svc-y"):
            board.write_header(run, tid)
        self.assertEqual(board.drift(run), [])

    def test_drift_ignores_assignee_and_flags_missing(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"}, "02-gone": {"repo": "r"}})
        board.write_header(run, "01-lib-x-a")
        p = run / "issues" / "01-lib-x-a.md"
        p.write_text(p.read_text().replace("**Assignee:** agent", "**Assignee:** bob")
                     .replace("**Related:** None\n", ""))
        d = board.drift(run)
        # a key absent from the file is not drift; only a missing file reports everything
        self.assertEqual([x for x in d if x["id"] == "01-lib-x-a"], [])
        self.assertEqual(len([x for x in d if x["id"] == "02-gone"]), len(board.HEADER_KEYS) - 1)

    def test_drift_on_020_shaped_file_only_flags_present_keys(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x", "slice": "01-s",
                                           "blocked_by": [{"id": "02-svc-y", "type": "merge"}]},
                            "02-svc-y": {"repo": "svc-y"}})
        (run / "issues" / "01-lib-x-a.md").write_text(
            "# Title\n\n**Slice:** 01-s\n**Repo:** other-repo\n\n**What to build:** x\n\n"
            "**Blocked by:** `01` (merge)\n\n**Interfaces:** none\n\n- [ ] ok\n")
        d = [x for x in board.drift(run) if x["id"] == "01-lib-x-a"]
        # only the contiguous bold header block is read; absent keys are not drift
        self.assertEqual({(x["key"], x["file"]) for x in d}, {("Repo", "other-repo")})

    def test_write_header_refuses_non_utf8_and_leaves_file(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"}})
        p = run / "issues" / "01-lib-x-a.md"
        raw = b"# T\n\nbody " + bytes([0xFF, 0xFE]) + b" text\n"
        p.write_bytes(raw)
        with self.assertRaises(UnicodeDecodeError):
            board.write_header(run, "01-lib-x-a")
        self.assertEqual(p.read_bytes(), raw)
        rc, out, _ = cli("header", "--run", str(run), "--id", "01-lib-x-a")
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(p.read_bytes(), raw)

    def test_write_header_does_not_treat_other_oserror_as_missing(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"}})
        (run / "issues" / "01-lib-x-a.md").mkdir()  # a directory: read raises IsADirectoryError
        with self.assertRaises(OSError):
            board.write_header(run, "01-lib-x-a")

    def test_write_header_leaves_no_temp_files(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"}})
        board.write_header(run, "01-lib-x-a")
        board.write_header(run, "01-lib-x-a")
        self.assertEqual([p.name for p in (run / "issues").iterdir()], ["01-lib-x-a.md"])

    def test_write_header_keeps_file_mode(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"}})
        f = run / "issues" / "01-lib-x-a.md"
        f.write_text("# a\n\nbody\n")
        f.chmod(0o640)
        board.write_header(run, "01-lib-x-a")
        self.assertEqual(f.stat().st_mode & 0o777, 0o640)

    def test_write_header_new_file_uses_umask(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"}})
        old = os.umask(0o022)
        try:
            board.write_header(run, "01-lib-x-a")
        finally:
            os.umask(old)
        self.assertEqual((run / "issues" / "01-lib-x-a.md").stat().st_mode & 0o777, 0o644)

    def test_cli(self):
        run = mk(self.tmp, {"01-lib-x-a": {"repo": "lib-x"}})
        rc, out, _ = cli("header", "--run", str(run), "--id", "01-lib-x-a")
        self.assertEqual((rc, json.loads(out)), (0, {"path": str(run / "issues" / "01-lib-x-a.md")}))
        rc, out, _ = cli("render", "--run", str(run))
        self.assertEqual((rc, json.loads(out)), (0, {"path": str(run / "issues" / "README.md")}))
        rc, out, _ = cli("drift", "--run", str(run))
        self.assertEqual((rc, json.loads(out)), (0, {"drift": []}))
        rc, out, err = cli("header", "--run", str(run), "--id", "nope")
        self.assertEqual((rc, out), (1, ""))
        self.assertTrue(err)
        rc, _, err = cli("render", "--run", str(Path(self.tmp) / "missing"))
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
