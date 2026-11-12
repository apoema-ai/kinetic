from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args],
                          capture_output=True, text=True, check=True)


def _sha256_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


class InstallCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.clone = self._make_clone(self.tmp / "clone", git=True)
        self.env = dict(os.environ,
                        HOME=str(self.home),
                        PYTHONPATH=str(self.clone / "scripts"))

    def _make_clone(self, path, git=True):
        path.mkdir(parents=True)
        if git:
            _git(path, "init")
        shutil.copytree(ROOT / "scripts", path / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "bin", path / "bin",
                        ignore=shutil.ignore_patterns("__pycache__"))
        return path

    def _run(self, clone, *args):
        env = dict(os.environ, HOME=str(self.home),
                   PYTHONPATH=str(clone / "scripts"))
        return subprocess.run([sys.executable, "-m", "kinetic", *args],
                              capture_output=True, text=True, env=env)

    def _install(self, *args, clone=None):
        return self._run(clone or self.clone, "install", *args)

    def _uninstall(self, harness="claude", clone=None):
        return self._install("--harness", harness, "--uninstall",
                             clone=clone)

    @property
    def link(self):
        return self.home / ".local" / "bin" / "kinetic"

    @property
    def settings_path(self):
        return self.home / ".config" / "kinetic" / "settings.json"

    @property
    def manifest_path(self):
        return self.home / ".config" / "kinetic" / "install-manifest-claude.json"

    def _settings(self):
        return json.loads(self.settings_path.read_text())

    def _manifest(self):
        return json.loads(self.manifest_path.read_text())


class InstallClaudeTest(InstallCase):
    def test_install_writes_link_settings_and_manifest(self):
        cfgdir = self.home / ".config" / "kinetic"
        cfgdir.mkdir(parents=True)
        self.settings_path.write_text(json.dumps({"tracker": "local"}))

        p = self._install("--harness", "claude")
        self.assertEqual(p.returncode, 0, p.stderr)

        target = str(self.clone / "bin" / "kinetic")
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(os.readlink(self.link), target)

        settings = self._settings()
        self.assertEqual(settings["harness"], "claude")
        self.assertEqual(settings["clone"], str(self.clone))
        self.assertEqual(settings["tracker"], "local")

        m = self._manifest()
        self.assertEqual(m["harness"], "claude")
        self.assertEqual(m["clone"], str(self.clone))
        entry = m["files"][str(self.link)]
        self.assertEqual(entry["type"], "symlink")
        self.assertEqual(entry["target"], target)
        self.assertEqual(entry["sha256"], _sha256_text(target))
        self.assertEqual(m["settings"]["path"], str(self.settings_path))
        self.assertEqual(m["settings"]["writes"],
                         {"harness": "claude", "clone": str(self.clone)})
        self.assertEqual(m["settings"]["previous"],
                         {"harness": None, "clone": None})

        # install output must tell the user the remaining manual step
        self.assertIn("--plugin-dir", p.stdout)
        self.assertIn(".local/bin", p.stdout)

    def test_installed_launcher_runs(self):
        p = self._install("--harness", "claude")
        self.assertEqual(p.returncode, 0, p.stderr)
        q = subprocess.run([str(self.link), "root"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(q.returncode, 0, q.stderr)
        self.assertEqual(q.stdout.strip(), str(self.clone))

    def test_install_via_clone_launcher(self):
        launcher = self.clone / "bin" / "kinetic"
        p = subprocess.run([sys.executable, str(launcher), "install",
                            "--harness", "claude"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.link.is_symlink())

    def test_install_is_idempotent(self):
        self.assertEqual(self._install("--harness", "claude").returncode, 0)
        first_manifest = self.manifest_path.read_text()
        first_settings = self.settings_path.read_text()
        p = self._install("--harness", "claude")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.manifest_path.read_text(), first_manifest)
        self.assertEqual(self.settings_path.read_text(), first_settings)

    def test_install_after_clone_move_replaces_own_link(self):
        self.assertEqual(self._install("--harness", "claude").returncode, 0)
        moved = self._make_clone(self.tmp / "clone2", git=True)
        p = self._install("--harness", "claude", clone=moved)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(os.readlink(self.link),
                         str(moved / "bin" / "kinetic"))
        self.assertEqual(self._settings()["clone"], str(moved))

    def test_install_refuses_foreign_file(self):
        bindir = self.home / ".local" / "bin"
        bindir.mkdir(parents=True)
        self.link.write_text("#!/bin/sh\necho foreign\n")
        p = self._install("--harness", "claude")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.link.read_text(), "#!/bin/sh\necho foreign\n")
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.settings_path.exists())

    def test_install_refuses_foreign_symlink(self):
        bindir = self.home / ".local" / "bin"
        bindir.mkdir(parents=True)
        self.link.symlink_to("/usr/bin/true")
        p = self._install("--harness", "claude")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(os.readlink(self.link), "/usr/bin/true")

    def test_install_requires_git_clone(self):
        nogit = self._make_clone(self.tmp / "nogit", git=False)
        p = self._install("--harness", "claude", clone=nogit)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("git", p.stderr.lower())
        self.assertFalse(self.link.exists())

    def test_unsupported_harness_writes_nothing(self):
        for hid in ("devin", "codex", "opencode"):
            p = self._install("--harness", hid)
            self.assertNotEqual(p.returncode, 0, hid)
            self.assertIn("not yet supported", p.stderr)
        self.assertFalse(self.link.exists())
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(list((self.home / ".config").rglob("*manifest*")))


class UninstallTest(InstallCase):
    def test_uninstall_removes_manifest_entries_and_nothing_else(self):
        sentinel = self.home / "sentinel.txt"
        sentinel.write_text("keep me")
        other = self.home / ".local" / "bin" / "other-tool"
        other.parent.mkdir(parents=True)
        other.write_text("x")
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text(json.dumps({"tracker": "local"}))

        self.assertEqual(self._install("--harness", "claude").returncode, 0)
        p = self._uninstall()
        self.assertEqual(p.returncode, 0, p.stderr)

        self.assertFalse(os.path.lexists(self.link))
        self.assertTrue(other.exists())
        self.assertTrue(sentinel.exists())
        self.assertEqual(self._settings(), {"tracker": "local"})
        self.assertFalse(self.manifest_path.exists())

    def test_uninstall_restores_previous_settings_values(self):
        self.settings_path.parent.mkdir(parents=True)
        before = {"harness": "devin", "clone": "/old/clone",
                  "tracker": "local"}
        self.settings_path.write_text(json.dumps(before))
        self.assertEqual(self._install("--harness", "claude").returncode, 0)
        p = self._uninstall()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self._settings(), before)

    def test_uninstall_removes_settings_file_it_created(self):
        self.assertEqual(self._install("--harness", "claude").returncode, 0)
        self.assertTrue(self.settings_path.exists())
        p = self._uninstall()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.settings_path.exists())

    def test_uninstall_without_install_is_a_noop(self):
        p = self._uninstall()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("nothing", p.stdout.lower() + p.stderr.lower())

    def test_uninstall_leaves_changed_link_target(self):
        self.assertEqual(self._install("--harness", "claude").returncode, 0)
        self.link.unlink()
        self.link.symlink_to("/usr/bin/true")
        p = self._uninstall()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.islink(self.link))


if __name__ == "__main__":
    unittest.main()
