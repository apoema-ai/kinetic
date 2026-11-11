from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kinetic.config import ConfigError, resolve


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.central = self.tmp / "repos.json"
        self.repo = self.tmp / "svc"
        self.repo.mkdir()

    def _central(self, data):
        self.central.write_text(json.dumps(data))

    def _repo(self, data):
        (self.repo / ".kinetic.json").write_text(json.dumps(data))

    def test_repo_override_wins(self):
        self._central({"svc": {"verify": "make test", "base_branch": "master"}})
        self._repo({"verify": "mvn verify"})
        self.assertEqual(
            resolve("svc", self.repo, self.central),
            {"verify": "mvn verify", "base_branch": "master", "publish_snapshot": None, "pin": None},
        )

    def test_default_base_branch_main(self):
        self._central({"svc": {"verify": "make test"}})
        self.assertEqual(resolve("svc", self.repo, self.central)["base_branch"], "main")

    def test_missing_verify_raises(self):
        with self.assertRaises(ConfigError) as ctx:
            resolve("svc", self.repo, self.central)
        self.assertEqual(
            str(ctx.exception),
            f"no verify command for repo 'svc': set it in {self.central} or {self.repo}/.kinetic.json",
        )

    def _raw(self, path, text):
        path.write_text(text)

    def test_malformed_config_raises_config_error(self):
        repo_file = self.repo / ".kinetic.json"
        cases = [
            (self.central, "{bad", str(self.central)),
            (self.central, "[]", str(self.central)),
            (self.central, '{"svc": "x"}', "svc"),
            (self.central, '{"svc": null}', "svc"),
            (repo_file, "{bad", str(repo_file)),
            (repo_file, "[]", str(repo_file)),
            (repo_file, '"x"', str(repo_file)),
        ]
        for path, text, needle in cases:
            for f in (self.central, repo_file):
                if f.exists():
                    f.unlink()
            self._raw(path, text)
            with self.assertRaises(ConfigError, msg=text) as ctx:
                resolve("svc", self.repo, self.central)
            self.assertIn(needle, str(ctx.exception))
            self.assertIn(str(path), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
