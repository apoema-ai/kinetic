from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ("jira mode", "Jira key:", "getJiraIssue")

# Harness-neutral text (spec Testing Decisions): no skill or agent names a
# Claude-only tool. ${CLAUDE_PLUGIN_ROOT} is deliberately absent here: the
# launcher sweep owns those invocation lines and is still in flight.
CLAUDE_ONLY_TOOLS = ("AskUserQuestion", "SendMessage", "run_in_background")

# No skill or agent body names a concrete model; model: stays in frontmatter
# as the Claude/Devin default.
CONCRETE_MODEL = re.compile(r"\b(sonnet|opus|haiku|gpt-[\w.-]+|claude-[\w.-]+)\b")

# The user-only skills carry both invocation keys; no other skill may
# carry triggers: (doctor keeps only disable-model-invocation, per rulings).
USER_ONLY_SKILLS = ("ask", "bare-clone", "bare-refresh", "bare-setup", "cleanup",
                    "implement", "init", "run", "status")

# Spec model tiers: implementer and fix-reviewer are standard; the reviewers and
# implementer-strong are strong. model: stays as the Claude/Devin default
# (sonnet for standard, opus for strong).
AGENT_TIERS = {
    "fix-reviewer": "standard",
    "implementer": "standard",
    "implementer-strong": "strong",
    "integration-reviewer": "strong",
    "spec-reviewer": "strong",
    "standards-reviewer": "strong",
}
TIER_MODELS = {"standard": "sonnet", "strong": "opus"}


def _text_files(*dirs):
    for d in dirs:
        for p in sorted((ROOT / d).rglob("*.md")):
            yield p


def _frontmatter(path):
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.S)
    return m.group(1) if m else None


def _body(path):
    text = path.read_text()
    m = re.match(r"---\n.*?\n---\n", text, re.S)
    return text[m.end():] if m else text


class SkillTextTest(unittest.TestCase):
    def test_no_jira_outside_adapters(self):
        bad = []
        for p in _text_files("skills", "agents"):
            text = p.read_text()
            for needle in FORBIDDEN:
                if needle in text:
                    bad.append("%s: %s" % (p.relative_to(ROOT), needle))
        self.assertEqual(bad, [])

    def test_no_claude_plugin_root_or_module_invocations(self):
        bad = []
        for p in _text_files("skills", "agents", "trackers"):
            text = p.read_text()
            for needle in ("${CLAUDE_PLUGIN_ROOT}", "PYTHONPATH",
                           "python3 -m kinetic"):
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

    def test_agents_declare_tier_beside_model(self):
        agents = sorted((ROOT / "agents").glob("*.md"))
        self.assertEqual({p.stem for p in agents}, set(AGENT_TIERS))
        for p in agents:
            fm = _frontmatter(p)
            self.assertIsNotNone(fm, str(p))
            tier = re.search(r"^tier:\s*(\S+)\s*$", fm, re.M)
            self.assertIsNotNone(tier, f"{p.name}: no tier: in frontmatter")
            self.assertEqual(tier.group(1), AGENT_TIERS[p.stem], p.name)
            model = re.search(r"^model:\s*(\S+)\s*$", fm, re.M)
            self.assertIsNotNone(model, f"{p.name}: no model: default")
            self.assertEqual(model.group(1), TIER_MODELS[tier.group(1)], p.name)

    def test_no_claude_only_tools(self):
        bad = []
        for p in _text_files("skills", "agents"):
            text = p.read_text()
            for needle in CLAUDE_ONLY_TOOLS:
                if needle in text:
                    bad.append("%s: %s" % (p.relative_to(ROOT), needle))
        self.assertEqual(bad, [])

    def test_no_concrete_model_in_body(self):
        bad = []
        for p in _text_files("skills", "agents"):
            for m in CONCRETE_MODEL.finditer(_body(p)):
                bad.append("%s: %s" % (p.relative_to(ROOT), m.group(0)))
        self.assertEqual(bad, [])

    def test_user_only_skills_have_both_invocation_keys(self):
        skills = sorted((ROOT / "skills").glob("**/SKILL.md"))
        self.assertTrue(skills)
        for p in skills:
            fm = _frontmatter(p)
            self.assertIsNotNone(fm, str(p))
            triggers = re.search(r"(?m)^triggers:", fm)
            if p.parent.name in USER_ONLY_SKILLS:
                self.assertIsNotNone(
                    re.search(r"(?m)^disable-model-invocation:\s*true\s*$", fm),
                    f"{p}: missing disable-model-invocation: true")
                self.assertIsNotNone(
                    re.search(r"(?m)^triggers:\s*\[user\]\s*$", fm),
                    f"{p}: missing triggers: [user]")
            else:
                self.assertIsNone(
                    triggers, f"{p}: triggers: belongs only on the user-only five")

    def test_implementer_strong_shares_implementer_body(self):
        self.assertEqual(
            _body(ROOT / "agents" / "implementer-strong.md"),
            _body(ROOT / "agents" / "implementer.md"))


if __name__ == "__main__":
    unittest.main()


class OrbitSkillTextTest(unittest.TestCase):
    def test_decompose_has_generic_publish_sentence(self):
        text = (ROOT / "skills/decompose/SKILL.md").read_text()
        self.assertIn("When the tracker adapter says it publishes staged tickets, follow the Local steps; "
                      "kinetic publishes them when the breakdown gate is approved.", text)
        self.assertNotIn("orbit", text.lower())

    def test_run_skill_records_the_ticket_store(self):
        text = (ROOT / "skills/run/SKILL.md").read_text()
        self.assertIn('--ticket-store "$(kinetic tracker store-record)"', text)

    def test_init_skill_offers_orbit(self):
        text = (ROOT / "skills/init/SKILL.md").read_text()
        self.assertIn("`orbit`", text)
