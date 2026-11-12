from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kinetic import harness


class ProfileTest(unittest.TestCase):
    def test_all_four_harnesses_have_complete_records(self):
        for hid in harness.HARNESS_IDS:
            p = harness.profile(hid)
            self.assertEqual(p["id"], hid)
            for key in ("name", "hooks", "tools", "resume_subagent",
                        "model_per_dispatch", "question_tool", "skill_dirs",
                        "agent_dirs", "instruction_files", "plugin_companions",
                        "plugin_store", "tier_defaults", "enforced"):
                self.assertIn(key, p, f"{hid}.{key}")
            for key in ("pre_tool_use", "post_tool_use", "session_start",
                        "stop", "trust"):
                self.assertIn(key, p["hooks"], f"{hid}.hooks.{key}")
            for key in ("shell", "edit", "patch"):
                self.assertIn(key, p["tools"], f"{hid}.tools.{key}")
            self.assertTrue(p["skill_dirs"])
            self.assertTrue(p["agent_dirs"])
            self.assertTrue(p["instruction_files"])
            for tier in ("standard", "strong"):
                self.assertIn(tier, p["tier_defaults"])

    def test_unknown_harness_raises(self):
        with self.assertRaises(harness.HarnessError):
            harness.profile("emacs")

    def test_enforced_and_instructed_partition_guarantees(self):
        for hid in harness.HARNESS_IDS:
            p = harness.profile(hid)
            enforced = set(p["enforced"])
            self.assertLessEqual(enforced, set(harness.GUARANTEES))
            self.assertEqual(set(harness.instructed(p)) | enforced, set(harness.GUARANTEES))
            self.assertFalse(set(harness.instructed(p)) & enforced)

    def test_claude_profile_values(self):
        p = harness.profile("claude")
        self.assertEqual(p["hooks"]["stop"], "block")
        self.assertTrue(p["resume_subagent"])
        self.assertTrue(p["model_per_dispatch"])
        self.assertEqual(p["question_tool"], "AskUserQuestion")
        self.assertEqual(p["skill_dirs"], ["~/.claude/skills"])
        self.assertEqual(p["agent_dirs"], ["~/.claude/agents"])
        self.assertEqual(p["instruction_files"], ["CLAUDE.md", "AGENTS.md"])
        self.assertTrue(p["plugin_companions"])
        self.assertEqual(harness.instructed(p), [])

    def test_codex_profile_values(self):
        p = harness.profile("codex")
        self.assertEqual(p["tools"]["shell"], "Bash")
        self.assertEqual(p["tools"]["patch"], "apply_patch")
        self.assertEqual(p["question_tool"], None)
        self.assertEqual(p["skill_dirs"], ["~/.agents/skills"])
        self.assertEqual(p["agent_dirs"], ["~/.codex/agents"])
        self.assertIn("/hooks", p["hooks"]["trust"])
        self.assertEqual(harness.instructed(p), [])

    def test_opencode_verify_gate_is_instructed(self):
        p = harness.profile("opencode")
        self.assertEqual(p["hooks"]["stop"], "reprompt")
        self.assertIn("verify-before-stop", harness.instructed(p))
        self.assertNotIn("verify-before-stop", p["enforced"])


class ActiveHarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = self.tmp / "settings.json"

    def test_flag_wins_over_settings(self):
        self.settings.write_text(json.dumps({"harness": "claude"}))
        self.assertEqual(harness.active_harness("codex", self.settings), "codex")

    def test_settings_harness_is_read(self):
        self.settings.write_text(json.dumps({"harness": "devin", "tracker": "local"}))
        self.assertEqual(harness.active_harness(None, self.settings), "devin")

    def test_missing_settings_defaults_to_claude(self):
        self.assertEqual(harness.active_harness(None, self.tmp / "nope.json"), "claude")
        self.settings.write_text("{}")
        self.assertEqual(harness.active_harness(None, self.settings), "claude")

    def test_invalid_settings_harness_raises(self):
        self.settings.write_text(json.dumps({"harness": "emacs"}))
        with self.assertRaises(harness.HarnessError):
            harness.active_harness(None, self.settings)

    def test_malformed_settings_raises(self):
        self.settings.write_text("{bad")
        with self.assertRaises(harness.HarnessError):
            harness.active_harness(None, self.settings)


class ResolveTierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = self.tmp / "settings.json"

    def _write(self, obj):
        self.settings.write_text(json.dumps(obj))

    def test_profile_defaults_per_harness(self):
        expected = {
            "claude": {"standard": {"model": "sonnet"},
                       "strong": {"model": "opus"}},
            "devin": {"standard": {"model": "sonnet"},
                      "strong": {"model": "opus"}},
            "codex": {"standard": {"model": "gpt-5.1-codex", "effort": "medium"},
                      "strong": {"model": "gpt-5.1-codex", "effort": "high"}},
            "opencode": {"standard": {"model": "anthropic/claude-sonnet-4-5"},
                         "strong": {"model": "anthropic/claude-opus-4-1"}},
        }
        missing = self.tmp / "missing.json"
        with mock.patch.object(harness, "DEFAULT_SETTINGS", missing):
            for hid, tiers in expected.items():
                for tier, want in tiers.items():
                    self.assertEqual(harness.resolve_tier(hid, tier, missing), want)
                    self.assertEqual(harness.resolve_tier(hid, tier), want)

    def test_settings_override_per_harness_and_tier(self):
        self._write({"tiers": {
            "codex": {"strong": {"model": "gpt-5.1-codex-max", "effort": "xhigh"}},
            "opencode": {"standard": {"model": "anthropic/claude-haiku-4-5"}},
        }})
        self.assertEqual(
            harness.resolve_tier("codex", "strong", self.settings),
            {"model": "gpt-5.1-codex-max", "effort": "xhigh"})
        self.assertEqual(
            harness.resolve_tier("opencode", "standard", self.settings),
            {"model": "anthropic/claude-haiku-4-5"})
        # Untouched tiers and harnesses keep their profile defaults.
        self.assertEqual(
            harness.resolve_tier("codex", "standard", self.settings),
            {"model": "gpt-5.1-codex", "effort": "medium"})
        self.assertEqual(
            harness.resolve_tier("opencode", "strong", self.settings),
            {"model": "anthropic/claude-opus-4-1"})

    def test_partial_override_keeps_profile_keys(self):
        self._write({"tiers": {"codex": {"strong": {"model": "gpt-5.1-codex-max"}}}})
        self.assertEqual(
            harness.resolve_tier("codex", "strong", self.settings),
            {"model": "gpt-5.1-codex-max", "effort": "high"})

    def test_override_does_not_leak_across_harnesses(self):
        self._write({"tiers": {"codex": {"standard": {"model": "other-model"}}}})
        self.assertEqual(
            harness.resolve_tier("claude", "standard", self.settings),
            {"model": "sonnet"})
        self.assertEqual(
            harness.resolve_tier("opencode", "standard", self.settings),
            {"model": "anthropic/claude-sonnet-4-5"})

    def test_unknown_harness_and_tier_raise(self):
        with self.assertRaises(harness.HarnessError):
            harness.resolve_tier("emacs", "standard", self.settings)
        with self.assertRaises(harness.HarnessError):
            harness.resolve_tier("codex", "turbo", self.settings)

    def test_malformed_tiers_raise(self):
        self._write({"tiers": ["not", "a", "dict"]})
        with self.assertRaises(harness.HarnessError):
            harness.resolve_tier("codex", "standard", self.settings)
        self._write({"tiers": {"codex": {"standard": "gpt-5"}}})
        with self.assertRaises(harness.HarnessError):
            harness.resolve_tier("codex", "standard", self.settings)
        self._write({"tiers": {"codex": {"standard": {"model": 42}}}})
        with self.assertRaises(harness.HarnessError):
            harness.resolve_tier("codex", "standard", self.settings)

    def test_bad_json_settings_raises(self):
        self.settings.write_text("{bad")
        with self.assertRaises(harness.HarnessError):
            harness.resolve_tier("codex", "standard", self.settings)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = self.tmp / "settings.json"

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(harness, "DEFAULT_SETTINGS", self.settings), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = harness.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_prints_profile_and_instructed_per_harness(self):
        for hid in harness.HARNESS_IDS:
            code, out, _ = self._run(["--harness", hid])
            self.assertEqual(code, 0, hid)
            self.assertIn(hid, out)
            self.assertIn("Enforced:", out)
            self.assertIn("Instructed:", out)
            instructed = harness.instructed(harness.profile(hid))
            if instructed:
                for g in instructed:
                    self.assertIn(g, out)

    def test_flag_overrides_settings_file(self):
        self.settings.write_text(json.dumps({"harness": "claude"}))
        code, out, _ = self._run(["--harness", "opencode"])
        self.assertEqual(code, 0)
        self.assertIn("opencode", out)
        self.assertIn("verify-before-stop", out)

    def test_settings_file_used_without_flag(self):
        self.settings.write_text(json.dumps({"harness": "codex"}))
        code, out, _ = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("codex", out)

    def test_no_settings_defaults_to_claude(self):
        code, out, _ = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("claude", out)

    def test_bad_settings_harness_fails(self):
        self.settings.write_text(json.dumps({"harness": "emacs"}))
        code, _, err = self._run([])
        self.assertNotEqual(code, 0)
        self.assertIn("emacs", err)


if __name__ == "__main__":
    unittest.main()
