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


if __name__ == "__main__":
    unittest.main()
