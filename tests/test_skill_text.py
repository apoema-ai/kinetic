from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ("jira mode", "Jira key:", "getJiraIssue")


def _text_files(*dirs):
    for d in dirs:
        for p in sorted((ROOT / d).rglob("*.md")):
            yield p


class SkillTextTest(unittest.TestCase):
    def test_no_jira_outside_adapters(self):
        bad = []
        for p in _text_files("skills", "agents"):
            text = p.read_text()
            for needle in FORBIDDEN:
                if needle in text:
                    bad.append("%s: %s" % (p.relative_to(ROOT), needle))
        self.assertEqual(bad, [])

    def test_implementer_has_needs_human(self):
        text = (ROOT / "agents" / "implementer.md").read_text()
        self.assertIn("NEEDS_HUMAN", text)
        self.assertIn("Manual step:", text)
        self.assertIn("Ticket ref:", text)
        self.assertIn("Tracker adapter:", text)

    def test_build_loop_mentions_only_human_left_and_human_done(self):
        text = (ROOT / "skills" / "run" / "guides" / "build-loop.md").read_text()
        for needle in ("only_human_left", "waiting_on_you", "human-done",
                       "NEEDS_HUMAN", "board drift", "-human-N"):
            self.assertIn(needle, text)
        human = text.index("- `only_human_left` is true")
        stalled = text.index("the loop is stalled on edges")
        self.assertLess(human, stalled)

    def test_all_frontmatter_parses(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("yaml not importable")
        paths = list((ROOT / "skills").glob("**/SKILL.md")) + list((ROOT / "agents").glob("*.md"))
        self.assertTrue(paths)
        for p in paths:
            m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S)
            self.assertIsNotNone(m, str(p))
            self.assertIsInstance(yaml.safe_load(m.group(1)), dict, str(p))


if __name__ == "__main__":
    unittest.main()
