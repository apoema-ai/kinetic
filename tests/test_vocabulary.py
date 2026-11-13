"""Kinetic's core stays independent of Orbit: only these places may name it."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("scripts", "hooks", "skills", "agents", "templates")
ALLOWED = {
    "scripts/kinetic/orbit_store.py",
    "skills/init/SKILL.md",
}
# tracker.py may name it only in the tracker registry (TRACKERS and REQUIRED).
REGISTRY = re.compile(r'^(TRACKERS = \(.*"orbit".*\)|    "orbit": \[\],)$')


class VocabularyTest(unittest.TestCase):
    def test_orbit_named_only_where_allowed(self):
        offenders = []
        for top in SCANNED:
            for path in sorted((ROOT / top).rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                rel = path.relative_to(ROOT).as_posix()
                if rel in ALLOWED:
                    continue
                for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                    if "orbit" not in line.lower():
                        continue
                    if rel == "scripts/kinetic/tracker.py" and REGISTRY.match(line):
                        continue
                    offenders.append(f"{rel}:{n}: {line.strip()}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_unqualified_adapter_for_ticket_store(self):
        for rel in ("scripts/kinetic/ticket_store.py", "scripts/kinetic/orbit_store.py"):
            text = (ROOT / rel).read_text()
            bad = [m.start() for m in re.finditer(r"\badapter\b", text)
                   if not text[max(0, m.start() - 8):m.start()].endswith("tracker ")]
            self.assertEqual(bad, [], rel)


if __name__ == "__main__":
    unittest.main()
