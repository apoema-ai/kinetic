from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kinetic import spec_lint

ROOT = Path(__file__).resolve().parent.parent

CLEAN = """# Spec

## Threat model
Attackers can replay requests.

## Non-functional requirements
p99 under 200ms.

## Acceptance criteria
- it works
"""


class SpecLintTest(unittest.TestCase):
    def test_lint_clean(self):
        self.assertEqual(spec_lint.lint(CLEAN), [])

    def test_lint_missing_threat_model(self):
        md = CLEAN.replace("## Threat model\nAttackers can replay requests.\n", "")
        problems = spec_lint.lint(md)
        self.assertEqual(len(problems), 1)
        self.assertIn("## Threat model", problems[0])

    def test_lint_empty_section(self):
        md = CLEAN.replace("p99 under 200ms.", "<!-- todo -->\n  ")
        problems = spec_lint.lint(md)
        self.assertEqual(len(problems), 1)
        self.assertIn("## Non-functional requirements", problems[0])

    def test_lint_empty_last_section_at_eof(self):
        problems = spec_lint.lint(CLEAN.replace("- it works\n", ""))
        self.assertEqual(len(problems), 1)
        self.assertIn("## Acceptance criteria", problems[0])

    def test_lint_wrong_level_heading_is_missing(self):
        problems = spec_lint.lint(CLEAN.replace("## Threat model", "### Threat model"))
        self.assertTrue(any("## Threat model" in p for p in problems))

    def test_lint_subheading_counts_as_empty(self):
        md = CLEAN.replace("Attackers can replay requests.", "## Other")
        self.assertTrue(any("Threat model" in p for p in spec_lint.lint(md)))

    def test_lint_level3_inside_section_is_content(self):
        md = CLEAN.replace("Attackers can replay requests.", "### Replay\nx")
        self.assertEqual(spec_lint.lint(md), [])

    def _cli(self, path):
        return subprocess.run([sys.executable, "-m", "kinetic.spec_lint", path],
                              capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")})

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d) / "ok.md"
            ok.write_text(CLEAN)
            bad = Path(d) / "bad.md"
            bad.write_text("# x\n")
            r = self._cli(str(ok))
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "[]"))
            self.assertEqual(self._cli(str(bad)).returncode, 1)
            self.assertEqual(self._cli(str(Path(d) / "nope.md")).returncode, 2)


if __name__ == "__main__":
    unittest.main()
