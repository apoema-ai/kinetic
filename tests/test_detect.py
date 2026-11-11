from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kinetic.detect_repos import propose


class ProposeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)

    def test_propose_maven(self):
        (self.d / "pom.xml").write_text("<project/>")
        self.assertEqual(propose(self.d), {"verify": "mvn -q verify", "marker": "pom.xml"})

    def test_propose_none(self):
        self.assertEqual(propose(self.d), {"verify": None, "marker": None})

    def test_makefile_needs_test_target(self):
        (self.d / "Makefile").write_text("build:\n\techo\n")
        self.assertIsNone(propose(self.d)["verify"])
        (self.d / "Makefile").write_text("build:\n\techo\ntest:\n\techo\n")
        self.assertEqual(propose(self.d), {"verify": "make test", "marker": "Makefile"})

    def test_first_match_wins(self):
        (self.d / "package.json").write_text("{}")
        (self.d / "pom.xml").write_text("<project/>")
        self.assertEqual(propose(self.d)["marker"], "pom.xml")


if __name__ == "__main__":
    unittest.main()
