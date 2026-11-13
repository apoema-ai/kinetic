from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from kinetic import catalog, config


class CatalogSettingTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(os.path.realpath(t.name))
        self.settings = self.tmp / "cfg" / "settings.json"

    def test_show_unset_is_none(self):
        self.assertIsNone(catalog.show(path=self.settings))
        out = io.StringIO()
        old = catalog.SETTINGS
        catalog.SETTINGS = self.settings
        self.addCleanup(setattr, catalog, "SETTINGS", old)
        with contextlib.redirect_stdout(out):
            rc = catalog.main(["show"])
        self.assertEqual(rc, 1)
        self.assertEqual(out.getvalue().strip(), "null")

    def test_set_saves_and_keeps_other_keys(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"tracker": "jira"}))
        d = self.tmp / "cat"
        d.mkdir()
        catalog.set_dir(str(d), path=self.settings)
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["tracker"], "jira")
        self.assertEqual(catalog.show(path=self.settings), str(d))

    def test_set_refuses_missing_dir_without_create(self):
        with self.assertRaisesRegex(ValueError, "not a directory"):
            catalog.set_dir(str(self.tmp / "nope"), path=self.settings)
        self.assertFalse(self.settings.exists())

    def test_set_create_makes_layout(self):
        d = self.tmp / "cat"
        out = catalog.set_dir(str(d), create=True, path=self.settings)
        self.assertEqual(out["created"], ["index.md", "terms.md", "repos", "recipes", "ledger.json"])
        self.assertEqual(json.loads((d / "ledger.json").read_text()), {})
        meta, _ = catalog.read_doc(d / "terms.md")
        self.assertEqual(meta, {"terms": {}})
        self.assertTrue(catalog.is_catalog(str(d)))

    def test_set_create_keeps_existing_files(self):
        d = self.tmp / "cat"
        d.mkdir()
        catalog.write_doc(d / "terms.md", {"terms": {"pledge": {"meaning": "m", "synonyms": [], "avoid": []}}}, "x\n")
        (d / "notes.txt").write_text("keep")
        before = (d / "terms.md").read_text()
        out = catalog.set_dir(str(d), create=True, path=self.settings)
        self.assertEqual(out["created"], ["index.md", "repos", "recipes", "ledger.json"])
        self.assertEqual((d / "terms.md").read_text(), before)
        self.assertEqual((d / "notes.txt").read_text(), "keep")

    def test_set_refuses_bad_json_settings(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text("{bad")
        d = self.tmp / "cat"
        d.mkdir()
        with self.assertRaises(config.ConfigError):
            catalog.set_dir(str(d), path=self.settings)
        self.assertEqual(self.settings.read_text(), "{bad")

    def test_detect_prefers_saved(self):
        d = self.tmp / "cat"
        catalog.set_dir(str(d), create=True, path=self.settings)
        out = catalog.detect(str(self.tmp), path=self.settings)
        self.assertEqual(out["existing_config"], str(d))
        self.assertEqual(out["recommendation"], str(d))
        self.assertEqual(out["candidates"][0], {"path": str(d), "reason": "saved"})

    def test_detect_finds_catalog_above_cwd(self):
        repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        cat = repo / "docs" / "catalog"
        catalog.init_layout(cat)
        out = catalog.detect(str(cat / "recipes"), path=self.settings)
        self.assertEqual(out["recommendation"], str(cat))
        self.assertEqual(out["candidates"][0]["reason"], "catalog at or above the current folder")

    def test_detect_none(self):
        out = catalog.detect(str(self.tmp), path=self.settings)
        self.assertIsNone(out["recommendation"])
        self.assertEqual(out["candidates"], [])


if __name__ == "__main__":
    unittest.main()
