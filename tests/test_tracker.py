from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kinetic.tracker import ROLES, ROOT, TRACKERS, TrackerError, adapter_defaults, pr_template, resolve


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = self.tmp / "settings.json"

    def _settings(self, data):
        self.settings.write_text(json.dumps(data))
        return self.settings

    def test_no_settings_is_local(self):
        r = resolve(settings=self.tmp / "missing.json")
        self.assertEqual(r["tracker"], "local")
        self.assertTrue(r["adapter"].endswith("trackers/local.md"))
        self.assertIsNone(r["description"])
        self.assertEqual(r["settings"], {})

    def test_legacy_jira_keys(self):
        s = self._settings({"tracker": "jira", "jira_project": "INV",
                            "slice_issue_type": "Epic", "child_issue_type": "Story"})
        r = resolve(settings=s)
        self.assertEqual(r["settings"], {"jira_project": "INV", "slice_issue_type": "Epic",
                                         "child_issue_type": "Story"})

    def test_tracker_settings_win_over_legacy(self):
        s = self._settings({"tracker": "jira", "jira_project": "OLD",
                            "tracker_settings": {"jira_project": "NEW", "slice_issue_type": "Epic",
                                                 "child_issue_type": "Story"}})
        self.assertEqual(resolve(settings=s)["settings"]["jira_project"], "NEW")

    def test_names_deep_merge(self):
        s = self._settings({"tracker": "local", "tracker_names": {"kind": {"human": "needs-ops"}}})
        names = resolve(settings=s)["names"]
        self.assertEqual(names["kind"], {"agent": "kind:agent", "human": "needs-ops"})
        self.assertEqual(names["status"]["todo"], "todo")

    def test_unknown_tracker_raises(self):
        with self.assertRaises(TrackerError):
            resolve(settings=self._settings({"tracker": "trello"}))

    def test_github_requires_repo(self):
        with self.assertRaises(TrackerError):
            resolve(settings=self._settings({"tracker": "github"}))
        r = resolve(settings=self._settings({"tracker": "github",
                                             "tracker_settings": {"github_repo": "org/repo"}}))
        self.assertEqual(r["settings"]["github_repo"], "org/repo")

    def test_other_requires_description(self):
        with self.assertRaises(TrackerError):
            resolve(settings=self._settings({"tracker": "other"}))
        r = resolve(settings=self._settings({"tracker": "other", "tracker_description": "use Notion"}))
        self.assertEqual(r["description"], "use Notion")

    def test_description_only_for_other(self):
        s = self._settings({"tracker": "local", "tracker_description": "ignored"})
        self.assertIsNone(resolve(settings=s)["description"])

    def test_non_dict_tracker_settings_raises(self):
        with self.assertRaises(TrackerError):
            resolve(settings=self._settings({"tracker": "local", "tracker_settings": "x"}))

    def test_non_dict_tracker_names_raises(self):
        with self.assertRaises(TrackerError):
            resolve(settings=self._settings({"tracker": "local", "tracker_names": ["x"]}))

    def test_names_overriding_group_with_string_raises(self):
        with self.assertRaises(TrackerError):
            resolve(settings=self._settings({"tracker": "local", "tracker_names": {"kind": "needs-ops"}}))

    def test_every_adapter_has_all_roles(self):
        for name in TRACKERS:
            path = ROOT / "trackers" / f"{name}.md"
            d = adapter_defaults(path)
            for role in ROLES:
                node = d
                for part in role.split("."):
                    self.assertIn(part, node, f"{name} lacks {role}")
                    node = node[part]

    def test_adapter_without_block_raises(self):
        p = self.tmp / "bad.md"
        p.write_text("no json here")
        with self.assertRaises(TrackerError):
            adapter_defaults(p)

    def test_pr_template_default(self):
        self.assertTrue(pr_template(None, settings=self.tmp / "missing.json").endswith("templates/pr-body.md"))

    def test_pr_template_repo_wins(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "mine.md").write_text("x")
        (repo / ".kinetic.json").write_text(json.dumps({"pr_template": "mine.md"}))
        other = self.tmp / "other.md"
        other.write_text("y")
        s = self._settings({"pr_template": str(other)})
        self.assertEqual(pr_template(repo, settings=s), str(repo / "mine.md"))

    def test_pr_template_settings_used_without_repo_config(self):
        other = self.tmp / "other.md"
        other.write_text("y")
        s = self._settings({"pr_template": str(other)})
        self.assertEqual(pr_template(self.tmp, settings=s), str(other))

    def test_pr_template_missing_file_raises(self):
        s = self._settings({"pr_template": str(self.tmp / "nope.md")})
        with self.assertRaises(TrackerError) as cm:
            pr_template(None, settings=s)
        self.assertIn("nope.md", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
