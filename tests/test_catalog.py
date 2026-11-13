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


def _recipe_meta():
    return {
        "slug": "onboard-asset-class", "title": "Onboard an asset class",
        "when": "adding a new <ASSET_CLASS> to the warehouse",
        "parameters": [{"name": "ASSET_CLASS", "meaning": "the asset class", "examples": ["HOME_SECURED"]}],
        "terms": ["warehouse"],
        "what_for": {"A": ["a1"], "B": ["b1", "b2"], "C": ["c1"]},
        "sources": [{"key": "K-1", "prs": [], "repos": ["A", "B", "C"]},
                    {"key": "K-2", "prs": [], "repos": ["A", "B"]},
                    {"key": "K-3", "prs": [], "repos": ["A"]}],
        "updated": "2026-11-13",
    }


def _terms(*names):
    return {"terms": {n: {"meaning": n, "synonyms": [], "avoid": []} for n in names}}


class CatalogFilesTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.d = Path(os.path.realpath(t.name)) / "cat"
        catalog.init_layout(self.d)

    def _good_catalog(self):
        catalog.write_doc(self.d / "terms.md", _terms("warehouse", "pledge"), "")
        meta = _recipe_meta()
        catalog.write_doc(self.d / "recipes" / "onboard-asset-class.md", meta, catalog.render_recipe(meta))
        repo = {"repo": "A", "org": "acme", "owns": "owns pledges",
                "terms": {"warehouse": ["K-1", "K-2"], "pledge": ["K-1"]}, "updated": "2026-11-13"}
        catalog.write_doc(self.d / "repos" / "A.md", repo, catalog.render_repo(repo))

    def test_doc_round_trip(self):
        p = self.d / "x.md"
        catalog.write_doc(p, {"a": [1, 2]}, "# body\n")
        self.assertEqual(catalog.read_doc(p), ({"a": [1, 2]}, "# body\n"))

    def test_read_doc_bad_frontmatter_names_file_and_line(self):
        p = self.d / "bad.md"
        p.write_text("---\n{bad\n---\nbody\n")
        with self.assertRaises(catalog.CatalogError) as cm:
            catalog.read_doc(p)
        self.assertIn(str(p), str(cm.exception))
        self.assertIn(":2:", str(cm.exception))

    def test_strength_thresholds(self):
        self.assertEqual(catalog.strength(1, 1), "seen once")
        self.assertEqual(catalog.strength(3, 3), "always")
        self.assertEqual(catalog.strength(2, 4), "usually")
        self.assertEqual(catalog.strength(3, 5), "usually")
        self.assertEqual(catalog.strength(2, 5), "sometimes")
        self.assertEqual(catalog.strength(1, 4), "seen once")

    def test_render_recipe_orders_and_labels_repos(self):
        body = catalog.render_recipe(_recipe_meta())
        heads = [l for l in body.splitlines() if l.startswith("## ")]
        self.assertEqual(heads, ["## A (always, 3 of 3)", "## B (usually, 2 of 3)",
                                 "## C (seen once, 1 of 3)"])
        self.assertIn("## B (usually, 2 of 3)\n- b1\n- b2\n", body)
        self.assertLess(body.index("**When to use:**"), body.index("## A"))

    def test_render_index_lists_recipes_and_repos(self):
        self._good_catalog()
        idx = catalog.render_index(catalog.load(self.d))
        self.assertIn("- onboard-asset-class — Onboard an asset class — adding a new <ASSET_CLASS> to the "
                      "warehouse — A (always), B (usually), C (seen once)", idx)
        self.assertIn("- A — warehouse (2), pledge (1)", idx)

    def test_ledger_lookup(self):
        catalog._write(self.d / "ledger.json", {"K-1": {"cataloged_at": "2026-11-13", "recipe": "r", "repos": ["A"]}})
        out = catalog.ledger_lookup(self.d, ["K-1", "K-2"])
        self.assertTrue(out["K-1"]["cataloged"])
        self.assertEqual(out["K-1"]["recipe"], "r")
        self.assertEqual(out["K-2"], {"cataloged": False})

    def test_lint_clean_catalog_is_empty(self):
        self._good_catalog()
        self.assertEqual(catalog.lint(self.d), [])

    def test_lint_reports_bad_frontmatter(self):
        self._good_catalog()
        (self.d / "repos" / "B.md").write_text("---\n{bad\n---\n")
        problems = catalog.lint(self.d)
        self.assertEqual(len(problems), 1)
        self.assertIn("B.md:2:", problems[0])

    def test_lint_reports_unknown_term(self):
        self._good_catalog()
        catalog.write_doc(self.d / "terms.md", _terms("warehouse"), "")
        problems = catalog.lint(self.d)
        self.assertTrue(any("pledge" in p and "A.md" in p for p in problems), problems)

    def test_index_rerenders_bodies_and_index(self):
        self._good_catalog()
        p = self.d / "recipes" / "onboard-asset-class.md"
        meta, body = catalog.read_doc(p)
        catalog.write_doc(p, meta, body + "\nhand edit\n")
        catalog.reindex(self.d)
        self.assertEqual(catalog.lint(self.d), [])
        self.assertIn("onboard-asset-class", (self.d / "index.md").read_text())

    def test_lint_reports_stale_recipe_body(self):
        self._good_catalog()
        p = self.d / "recipes" / "onboard-asset-class.md"
        meta, body = catalog.read_doc(p)
        catalog.write_doc(p, meta, body + "\nhand edit\n")
        self.assertTrue(any("onboard-asset-class.md" in x and "body" in x for x in catalog.lint(self.d)))


def _change(key, repos, recipe="onboard-asset-class", what_for=None, new_terms=("warehouse",)):
    ch = {
        "deliverables": [{"key": key, "repos": list(repos), "prs": [f"https://x/{key}"], "recipe": recipe}],
        "recipes": [],
        "repos": [{"repo": r, "org": "acme", "terms": {"warehouse": [key]}} for r in repos],
        "terms": [{"term": t, "meaning": t, "synonyms": [], "avoid": []} for t in new_terms],
    }
    if recipe:
        ch["recipes"].append({"slug": recipe, "title": "Onboard an asset class",
                              "when": "adding a new <ASSET_CLASS>",
                              "parameters": [{"name": "ASSET_CLASS", "meaning": "class", "examples": []}],
                              "terms": ["warehouse"],
                              "what_for": what_for if what_for is not None else {r: [f"{r} work"] for r in repos}})
    return ch


class CatalogApplyTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.d = Path(os.path.realpath(t.name)) / "cat"
        catalog.init_layout(self.d)

    def _snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.d.rglob("*") if p.is_file()}

    def _recipe(self):
        return catalog.read_doc(self.d / "recipes" / "onboard-asset-class.md")

    def test_apply_creates_recipe_profiles_terms_and_ledger(self):
        out = catalog.apply(self.d, _change("K-1", ["A"]), today="2026-11-13")
        self.assertIn("recipes/onboard-asset-class.md", out["written"])
        meta, body = self._recipe()
        self.assertIn("## A (seen once, 1 of 1)", body)
        self.assertEqual(meta["sources"], [{"key": "K-1", "prs": ["https://x/K-1"], "repos": ["A"]}])
        self.assertEqual(catalog.read_doc(self.d / "repos" / "A.md")[0]["terms"], {"warehouse": ["K-1"]})
        self.assertIn("warehouse", catalog.read_doc(self.d / "terms.md")[0]["terms"])
        self.assertEqual(json.loads((self.d / "ledger.json").read_text())["K-1"],
                         {"cataloged_at": "2026-11-13", "recipe": "onboard-asset-class", "repos": ["A"]})
        self.assertIn("onboard-asset-class", (self.d / "index.md").read_text())
        self.assertEqual(catalog.lint(self.d), [])

    def test_apply_second_deliverable_raises_counts_and_adds_seen_once_repo(self):
        catalog.apply(self.d, _change("K-1", ["A", "B"]), today="2026-11-13")
        catalog.apply(self.d, _change("K-2", ["A", "B", "D"], new_terms=()), today="2026-11-14")
        _, body = self._recipe()
        self.assertIn("## A (always, 2 of 2)", body)
        self.assertIn("## D (seen once, 1 of 2)", body)
        self.assertEqual(catalog.read_doc(self.d / "repos" / "A.md")[0]["terms"], {"warehouse": ["K-1", "K-2"]})

    def test_apply_keeps_what_for_of_repos_not_named(self):
        catalog.apply(self.d, _change("K-1", ["A", "B"]), today="2026-11-13")
        catalog.apply(self.d, _change("K-2", ["A"], what_for={"A": ["new A"]}, new_terms=()), today="2026-11-14")
        meta, _ = self._recipe()
        self.assertEqual(meta["what_for"], {"A": ["new A"], "B": ["B work"]})

    def test_apply_refuses_key_already_in_ledger(self):
        catalog.apply(self.d, _change("K-1", ["A"]), today="2026-11-13")
        before = self._snapshot()
        with self.assertRaisesRegex(catalog.CatalogError, "K-1"):
            catalog.apply(self.d, _change("K-1", ["A"], new_terms=()), today="2026-11-14")
        self.assertEqual(self._snapshot(), before)

    def test_apply_refuses_unknown_term(self):
        before = self._snapshot()
        with self.assertRaisesRegex(catalog.CatalogError, "warehouse"):
            catalog.apply(self.d, _change("K-1", ["A"], new_terms=()), today="2026-11-13")
        self.assertEqual(self._snapshot(), before)

    def test_apply_refuses_unknown_recipe_slug(self):
        ch = _change("K-1", ["A"])
        ch["recipes"] = []
        before = self._snapshot()
        with self.assertRaisesRegex(catalog.CatalogError, "onboard-asset-class"):
            catalog.apply(self.d, ch, today="2026-11-13")
        self.assertEqual(self._snapshot(), before)

    def test_apply_refuses_when_catalog_file_is_broken(self):
        (self.d / "repos" / "Z.md").write_text("---\n{bad\n---\n")
        before = self._snapshot()
        with self.assertRaises(catalog.CatalogError):
            catalog.apply(self.d, _change("K-1", ["A"]), today="2026-11-13")
        self.assertEqual(self._snapshot(), before)

    def test_apply_deliverable_without_recipe_goes_to_ledger_only(self):
        catalog.apply(self.d, _change("K-1", ["A"], recipe=None), today="2026-11-13")
        self.assertEqual(list((self.d / "recipes").glob("*.md")), [])
        self.assertIsNone(json.loads((self.d / "ledger.json").read_text())["K-1"]["recipe"])
        self.assertTrue((self.d / "repos" / "A.md").is_file())

    def test_cli_apply_without_catalog_dir_exits_1(self):
        f = self.d.parent / "changes.json"
        f.write_text(json.dumps(_change("K-1", ["A"])))
        old = catalog.SETTINGS
        catalog.SETTINGS = self.d.parent / "settings.json"
        self.addCleanup(setattr, catalog, "SETTINGS", old)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = catalog.main(["apply", "--changes", str(f)])
        self.assertEqual(rc, 1)
        self.assertIn("catalog-setup", err.getvalue())


if __name__ == "__main__":
    unittest.main()
