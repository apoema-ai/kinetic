from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
LAUNCHER = ROOT / "bin" / "kinetic"


def _env(**extra):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS)
    env.update(extra)
    return env


def _run_module(*args, **env_extra):
    return subprocess.run([sys.executable, "-m", "kinetic", *args],
                          capture_output=True, text=True, env=_env(**env_extra))


class DispatcherTest(unittest.TestCase):
    def test_root_prints_clone_root(self):
        p = _run_module("root")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), str(ROOT))

    def test_dispatches_to_module_main(self):
        p = _run_module("harness", "--harness", "claude")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Harness: Claude Code (claude)", p.stdout)

    def test_dispatch_passes_args_through(self):
        p = _run_module("status")  # missing --run -> module's own error
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("status", p.stderr + p.stdout)

    def test_unknown_command_fails(self):
        p = _run_module("frobnicate")
        self.assertEqual(p.returncode, 2)
        self.assertIn("frobnicate", p.stderr)

    def test_no_args_prints_usage(self):
        p = _run_module()
        self.assertEqual(p.returncode, 2)
        self.assertIn("usage", p.stderr.lower() + p.stdout.lower())

    def test_install_is_a_module(self):
        p = _run_module("install", "--help")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("--harness", p.stdout)


class LauncherTest(unittest.TestCase):
    def test_bin_kinetic_root(self):
        p = subprocess.run([sys.executable, str(LAUNCHER), "root"],
                           capture_output=True, text=True, env=_env())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), str(ROOT))

    def test_bin_kinetic_dispatches(self):
        p = subprocess.run([sys.executable, str(LAUNCHER), "harness",
                            "--harness", "devin"],
                           capture_output=True, text=True, env=_env())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Devin CLI (devin)", p.stdout)

    def test_symlinked_launcher_resolves_clone(self):
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / "kinetic"
            link.symlink_to(LAUNCHER)
            p = subprocess.run([sys.executable, str(link), "root"],
                               capture_output=True, text=True, env=_env())
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout.strip(), str(ROOT))


if __name__ == "__main__":
    unittest.main()
