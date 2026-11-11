from __future__ import annotations

import re
import unittest

from kinetic.tracker import ROOT

PLACEHOLDERS = {
    "TICKETS", "TITLE_KEY", "DESCRIPTION", "DESIGN_DECISIONS", "ARCHITECTURE",
    "ATTENTION_POINTS", "MANUAL_STEPS", "SHIPS_WITH", "RELATED_PRS", "DEPENDS_ON",
}


class TemplateTests(unittest.TestCase):
    def test_default_template_has_all_placeholders(self):
        text = (ROOT / "templates" / "pr-body.md").read_text()
        self.assertEqual(set(re.findall(r"<<([A-Z_]+)>>", text)), PLACEHOLDERS)

    def test_ship_skill_does_not_inline_layout(self):
        text = (ROOT / "skills" / "ship" / "SKILL.md").read_text()
        self.assertNotIn("### Tickets:\n- <KEY", text)
        self.assertIn("kinetic.tracker pr-template", text)


if __name__ == "__main__":
    unittest.main()
