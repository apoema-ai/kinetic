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
from unittest import mock

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
        # every HARNESS_IDS member is supported now; an unknown id is
        # rejected by argparse before anything is written
        p = self._install("--harness", "bogus")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("bogus", p.stderr)
        self.assertFalse(self.link.exists())
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(list((self.home / ".config").rglob("*manifest*")))


class InstallDevinTest(InstallCase):
    """`kinetic install --harness devin` shells out to `devin` on PATH; tests
    fake it with a script that records argv and simulates the plugin store."""

    def setUp(self):
        super().setUp()
        self.base_path = os.environ.get("PATH", "")
        self.bin = self.tmp / "devin-bin"
        self.bin.mkdir()
        self.devin_log = self.tmp / "devin.log"
        self.devin_state = self.tmp / "devin-state"
        devin = self.bin / "devin"
        devin.write_text(
            "#!/bin/sh\n"
            f"echo \"$@\" >> {self.devin_log}\n"
            "if [ \"$1\" = plugins ] && [ \"$2\" = install ]; then\n"
            "  if [ \"${DEVIN_INSTALL_RC:-0}\" != 0 ]; then\n"
            "    echo 'devin: install failed' >&2\n"
            "    exit \"$DEVIN_INSTALL_RC\"\n"
            "  fi\n"
            f"  if [ -f {self.devin_state} ] && "
            f"grep -qx kinetic {self.devin_state}; then\n"
            "    echo 'devin: already installed' >&2\n"
            "    exit 1\n"
            "  fi\n"
            f"  echo kinetic >> {self.devin_state}\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = plugins ] && [ \"$2\" = list ]; then\n"
            f"  [ -f {self.devin_state} ] && cat {self.devin_state}\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = plugins ] && [ \"$2\" = remove ]; then\n"
            f"  if [ -f {self.devin_state} ]; then\n"
            f"    grep -vx \"$3\" {self.devin_state} > {self.devin_state}.tmp"
            f" && mv {self.devin_state}.tmp {self.devin_state}\n"
            "  fi\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n")
        devin.chmod(0o755)
        patcher = mock.patch.dict(
            os.environ, {"PATH": f"{self.bin}:{self.base_path}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def devin_config(self):
        return self.home / ".config" / "devin" / "config.json"

    @property
    def manifest_path(self):
        return (self.home / ".config" / "kinetic"
                / "install-manifest-devin.json")

    def _devin_calls(self):
        if not self.devin_log.exists():
            return []
        return [l.strip() for l in
                self.devin_log.read_text().splitlines() if l.strip()]

    def _devin_hook_commands(self, cfg):
        return [h.get("command", "")
                for groups in (cfg.get("hooks") or {}).values()
                for g in groups
                for h in (g.get("hooks") or [])]

    def test_install_runs_plugin_install_and_writes_state(self):
        p = self._install("--harness", "devin")
        self.assertEqual(p.returncode, 0, p.stderr)

        self.assertIn(f"plugins install --local {self.clone}",
                      self._devin_calls())

        self.assertTrue(self.link.is_symlink())
        settings = self._settings()
        self.assertEqual(settings["harness"], "devin")
        self.assertEqual(settings["clone"], str(self.clone))

        m = json.loads(self.manifest_path.read_text())
        self.assertEqual(m["harness"], "devin")
        self.assertEqual(m["clone"], str(self.clone))
        self.assertEqual(m["plugin"]["name"], "kinetic")
        self.assertEqual(Path(m["devin_config"]["path"]), self.devin_config)
        self.assertFalse(m["devin_config"]["existed"])

        cfg = json.loads(self.devin_config.read_text())
        cmds = self._devin_hook_commands(cfg)
        self.assertEqual(len([c for c in cmds if "--harness devin" in c]), 7)
        self.assertTrue(any("isolation.py" in c and str(self.clone) in c
                            for c in cmds))
        self.assertTrue(any("completion_gate.py" in c for c in cmds))
        self.assertTrue(any("orient.py" in c for c in cmds))
        matchers = " ".join(g.get("matcher", "")
                            for g in cfg["hooks"]["PreToolUse"])
        self.assertIn("exec", matchers)
        self.assertIn("edit|write", matchers)
        self.assertIn("/kinetic:", p.stdout)

    def test_install_devin_is_idempotent(self):
        self.assertEqual(self._install("--harness", "devin").returncode, 0)
        first_cfg = self.devin_config.read_text()
        first_manifest = self.manifest_path.read_text()
        first_settings = self.settings_path.read_text()
        p = self._install("--harness", "devin")
        self.assertEqual(p.returncode, 0, p.stderr)
        # second run: fake devin rejects the duplicate install; the installer
        # falls back to `devin plugins list` and continues
        self.assertIn("already installed", p.stdout)
        self.assertEqual(self.devin_config.read_text(), first_cfg)
        self.assertEqual(self.manifest_path.read_text(), first_manifest)
        self.assertEqual(self.settings_path.read_text(), first_settings)

    def test_install_devin_preserves_foreign_config_and_hooks(self):
        self.devin_config.parent.mkdir(parents=True)
        foreign = {"permissions": {"allow": ["Exec(ls)"]},
                   "agent": {"model": "gpt-5"},
                   "hooks": {"PreToolUse": [
                       {"matcher": "exec",
                        "hooks": [{"type": "command",
                                   "command": "echo foreign"}]}]}}
        self.devin_config.write_text(json.dumps(foreign))
        p = self._install("--harness", "devin")
        self.assertEqual(p.returncode, 0, p.stderr)

        cfg = json.loads(self.devin_config.read_text())
        self.assertEqual(cfg["permissions"], foreign["permissions"])
        self.assertEqual(cfg["agent"], foreign["agent"])
        pre = cfg["hooks"]["PreToolUse"]
        self.assertTrue(any(h["command"] == "echo foreign"
                            for g in pre for h in g["hooks"]))
        self.assertTrue(any("--harness devin" in h["command"]
                            for g in pre for h in g["hooks"]))

        # re-run converges: foreign entries kept, ours not duplicated
        p = self._install("--harness", "devin")
        self.assertEqual(p.returncode, 0, p.stderr)
        cfg2 = json.loads(self.devin_config.read_text())
        cmds = self._devin_hook_commands(cfg2)
        self.assertEqual(len([c for c in cmds if "--harness devin" in c]), 7)
        self.assertTrue(any(h["command"] == "echo foreign"
                            for g in cfg2["hooks"]["PreToolUse"]
                            for h in g["hooks"]))

    def test_install_devin_replaces_stale_clone_paths(self):
        self.assertEqual(self._install("--harness", "devin").returncode, 0)
        moved = self._make_clone(self.tmp / "clone2", git=True)
        p = self._install("--harness", "devin", clone=moved)
        self.assertEqual(p.returncode, 0, p.stderr)
        cfg = json.loads(self.devin_config.read_text())
        cmds = self._devin_hook_commands(cfg)
        self.assertTrue(all(str(moved) in c for c in cmds
                            if "--harness devin" in c))
        # "/clone/" must not match "/clone2/" — compare path segments
        self.assertFalse(any(str(self.clone) + "/" in c for c in cmds))

    def test_install_devin_fails_without_cli(self):
        with mock.patch.dict(os.environ, {"PATH": self.base_path}):
            p = self._install("--harness", "devin")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("devin", p.stderr.lower())
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(self.devin_config.exists())

    def test_install_devin_plugin_failure_aborts_before_writes(self):
        with mock.patch.dict(os.environ, {"DEVIN_INSTALL_RC": "3"}):
            p = self._install("--harness", "devin")
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(self.link.exists())
        self.assertFalse(self.devin_config.exists())

    def test_install_devin_rejects_malformed_config(self):
        self.devin_config.parent.mkdir(parents=True)
        self.devin_config.write_text(json.dumps({"hooks": []}))
        p = self._install("--harness", "devin")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("hooks", p.stderr)
        # preflight fails before the plugin install is attempted
        self.assertFalse(self.devin_log.exists())
        self.assertEqual(self.devin_config.read_text(),
                         json.dumps({"hooks": []}))

    # --- uninstall ---------------------------------------------------------

    def test_uninstall_removes_everything_it_wrote(self):
        self.assertEqual(self._install("--harness", "devin").returncode, 0)
        p = self._uninstall("devin")
        self.assertEqual(p.returncode, 0, p.stderr)

        self.assertIn("plugins remove kinetic --local", self._devin_calls())
        self.assertFalse(os.path.lexists(self.link))
        self.assertFalse(self.settings_path.exists())
        # the config held only our hooks -> the file we created is gone
        self.assertFalse(self.devin_config.exists())
        self.assertFalse(self.manifest_path.exists())

    def test_uninstall_devin_restores_foreign_config(self):
        self.devin_config.parent.mkdir(parents=True)
        self.devin_config.write_text(json.dumps(
            {"permissions": {"allow": ["Exec(ls)"]}}))
        self.assertEqual(self._install("--harness", "devin").returncode, 0)
        p = self._uninstall("devin")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.devin_config.read_text()),
                         {"permissions": {"allow": ["Exec(ls)"]}})

    def test_uninstall_devin_without_cli_still_cleans(self):
        self.assertEqual(self._install("--harness", "devin").returncode, 0)
        with mock.patch.dict(os.environ, {"PATH": self.base_path}):
            p = self._uninstall("devin")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("devin", p.stderr.lower())
        self.assertFalse(self.devin_config.exists())
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(os.path.lexists(self.link))

    def test_uninstall_devin_leaves_changed_foreign_hooks(self):
        self.devin_config.parent.mkdir(parents=True)
        self.devin_config.write_text(json.dumps({"hooks": {"Stop": [
            {"matcher": "",
             "hooks": [{"type": "command", "command": "echo foreign"}]}]}}))
        self.assertEqual(self._install("--harness", "devin").returncode, 0)
        p = self._uninstall("devin")
        self.assertEqual(p.returncode, 0, p.stderr)
        cfg = json.loads(self.devin_config.read_text())
        self.assertEqual(cfg["hooks"]["Stop"][0]["hooks"][0]["command"],
                         "echo foreign")
        cmds = self._devin_hook_commands(cfg)
        self.assertFalse(any("--harness devin" in c for c in cmds))


class InstallCodexTest(InstallCase):
    """`kinetic install --harness codex` generates files only: kntc-<name>
    stub skills under ~/.agents/skills, agent TOML under ~/.codex/agents and
    a merged ~/.codex/hooks.json. It never shells out to codex (hook trust is
    a manual /hooks step); it only requires the CLI on PATH."""

    USER_ONLY = {"ask", "doctor", "implement", "init", "run", "status"}
    SKILL_NAMES = {"ask", "doctor", "grill", "implement", "init", "retro",
                   "run", "ship", "spec", "status", "tdd", "tickets"}
    AGENT_NAMES = {"fix-reviewer", "implementer", "implementer-strong",
                   "integration-reviewer", "spec-reviewer",
                   "standards-reviewer"}

    def setUp(self):
        super().setUp()
        # the codex installer reads skills/ and agents/ from the clone
        shutil.copytree(ROOT / "skills", self.clone / "skills",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "agents", self.clone / "agents",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.base_path = os.environ.get("PATH", "")
        self.bin = self.tmp / "codex-bin"
        self.bin.mkdir()
        codex = self.bin / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(0o755)
        patcher = mock.patch.dict(
            os.environ, {"PATH": f"{self.bin}:{self.base_path}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def skills_dir(self):
        return self.home / ".agents" / "skills"

    @property
    def agents_dir(self):
        return self.home / ".codex" / "agents"

    @property
    def hooks_json(self):
        return self.home / ".codex" / "hooks.json"

    @property
    def manifest_path(self):
        return (self.home / ".config" / "kinetic"
                / "install-manifest-codex.json")

    def _hook_commands(self, cfg=None):
        cfg = cfg if cfg is not None else json.loads(
            self.hooks_json.read_text())
        return [h.get("command", "")
                for groups in (cfg.get("hooks") or {}).values()
                for g in groups
                for h in (g.get("hooks") or [])]

    def _stub(self, name):
        return self.skills_dir / f"kntc-{name}" / "SKILL.md"

    def _skill_frontmatter(self, path):
        text = path.read_text()
        assert text.startswith("---\n")
        fm = text.split("---\n", 2)[1]
        return fm

    def test_install_writes_stubs_agents_hooks_and_state(self):
        p = self._install("--harness", "codex")
        self.assertEqual(p.returncode, 0, p.stderr)

        self.assertTrue(self.link.is_symlink())
        settings = self._settings()
        self.assertEqual(settings["harness"], "codex")
        self.assertEqual(settings["clone"], str(self.clone))

        # one kntc-<name> stub per skill
        for name in self.SKILL_NAMES:
            stub = self._stub(name)
            self.assertTrue(stub.is_file(), name)
            text = stub.read_text()
            self.assertIn(f"name: kntc-{name}", text)
            # the description is YAML-quoted because it contains ": "
            self.assertIn('description: "kinetic: ', text)
            self.assertIn(f"{self.clone}/skills/{name}/SKILL.md", text)

        # user-only skills get agents/openai.yaml disabling implicit invocation
        for name in self.SKILL_NAMES:
            oy = (self.skills_dir / f"kntc-{name}" / "agents"
                  / "openai.yaml")
            if name in self.USER_ONLY:
                self.assertTrue(oy.is_file(), name)
                self.assertIn("allow_implicit_invocation: false",
                              oy.read_text())
            else:
                self.assertFalse(oy.exists(), name)

        # agent TOML files, one per agents/*.md
        for name in self.AGENT_NAMES:
            toml_path = self.agents_dir / f"{name}.toml"
            self.assertTrue(toml_path.is_file(), name)
            text = toml_path.read_text()
            self.assertIn(f'name = "{name}"', text)
            self.assertIn("developer_instructions", text)
            self.assertIn("model = ", text)
            self.assertIn("model_reasoning_effort = ", text)
        impl = (self.agents_dir / "implementer.toml").read_text()
        strong = (self.agents_dir / "implementer-strong.toml").read_text()
        self.assertIn('name = "kntc-tdd"', impl)
        self.assertIn('name = "kntc-tdd"', strong)
        # tier -> model mapping: strong resolves differently than standard
        from kinetic import harness as _h
        std = _h.resolve_tier("codex", "standard",
                              settings=self.settings_path)
        sst = _h.resolve_tier("codex", "strong",
                              settings=self.settings_path)
        self.assertIn(f'model = "{std["model"]}"', impl)
        self.assertIn(f'model = "{sst["model"]}"', strong)
        self.assertIn(f'model_reasoning_effort = "{std["effort"]}"', impl)
        self.assertIn(f'model_reasoning_effort = "{sst["effort"]}"',
                      strong)

        # hooks.json: seven kinetic entries marked --harness codex
        cmds = self._hook_commands()
        ours = [c for c in cmds if "--harness codex" in c]
        self.assertEqual(len(ours), 7)
        self.assertTrue(any("isolation.py" in c and str(self.clone) in c
                            for c in ours))
        self.assertTrue(any("completion_gate.py" in c for c in ours))
        self.assertTrue(any("orient.py" in c for c in ours))
        self.assertIn("/hooks", p.stdout)
        self.assertIn("kntc-", p.stdout)

        m = json.loads(self.manifest_path.read_text())
        self.assertEqual(m["harness"], "codex")
        self.assertEqual(m["clone"], str(self.clone))
        # every generated file is manifest-listed for staleness checks
        for f in (self._stub("run"), self.agents_dir / "implementer.toml"):
            self.assertIn(str(f), m["files"])

    def test_install_codex_is_idempotent(self):
        self.assertEqual(self._install("--harness", "codex").returncode, 0)
        first_hooks = self.hooks_json.read_text()
        first_manifest = self.manifest_path.read_text()
        p = self._install("--harness", "codex")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.hooks_json.read_text(), first_hooks)
        self.assertEqual(self.manifest_path.read_text(), first_manifest)

    def test_install_codex_preserves_foreign_hooks(self):
        self.hooks_json.parent.mkdir(parents=True)
        foreign = {"description": "user hooks",
                   "hooks": {"PreToolUse": [
                       {"matcher": "Bash",
                        "hooks": [{"type": "command",
                                   "command": "echo foreign"}]}],
                       "Stop": [{"hooks": [{"type": "command",
                                             "command": "echo bye"}]}]}}
        self.hooks_json.write_text(json.dumps(foreign))
        p = self._install("--harness", "codex")
        self.assertEqual(p.returncode, 0, p.stderr)

        cfg = json.loads(self.hooks_json.read_text())
        self.assertEqual(cfg["description"], "user hooks")
        pre = cfg["hooks"]["PreToolUse"]
        self.assertTrue(any(h["command"] == "echo foreign"
                            for g in pre for h in g["hooks"]))
        self.assertTrue(any("--harness codex" in h["command"]
                            for g in pre for h in g["hooks"]))
        self.assertTrue(any(h["command"] == "echo bye"
                            for g in cfg["hooks"]["Stop"]
                            for h in g["hooks"]))

        # re-run converges: foreign entries kept, ours not duplicated
        p = self._install("--harness", "codex")
        self.assertEqual(p.returncode, 0, p.stderr)
        cmds = self._hook_commands()
        self.assertEqual(len([c for c in cmds if "--harness codex" in c]), 7)
        self.assertIn("echo foreign", cmds)
        self.assertIn("echo bye", cmds)

    def test_install_codex_replaces_stale_clone_paths(self):
        self.assertEqual(self._install("--harness", "codex").returncode, 0)
        moved = self.tmp / "clone2"
        shutil.copytree(self.clone, moved, symlinks=True)
        _git(moved, "init")
        p = self._install("--harness", "codex", clone=moved)
        self.assertEqual(p.returncode, 0, p.stderr)
        cmds = [c for c in self._hook_commands() if "--harness codex" in c]
        self.assertTrue(cmds)
        self.assertTrue(all(str(moved) in c for c in cmds))
        self.assertFalse(any(str(self.clone) + "/" in c for c in cmds))
        # stubs point at the new clone too
        self.assertIn(str(moved), self._stub("run").read_text())

    def test_install_codex_fails_without_cli(self):
        # a PATH with git (needed by the clone check) but no codex
        nogit = self.tmp / "no-codex-bin"
        nogit.mkdir()
        (nogit / "git").symlink_to(shutil.which("git"))
        with mock.patch.dict(os.environ, {"PATH": str(nogit)}):
            p = self._install("--harness", "codex")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("codex", p.stderr.lower())
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(self.hooks_json.exists())

    def test_install_codex_rejects_malformed_hooks_json(self):
        self.hooks_json.parent.mkdir(parents=True)
        self.hooks_json.write_text(json.dumps({"hooks": []}))
        p = self._install("--harness", "codex")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("hooks", p.stderr)
        self.assertEqual(self.hooks_json.read_text(),
                         json.dumps({"hooks": []}))
        self.assertFalse(self.manifest_path.exists())

    # --- uninstall ---------------------------------------------------------

    def test_uninstall_codex_removes_everything_it_wrote(self):
        self.assertEqual(self._install("--harness", "codex").returncode, 0)
        p = self._uninstall("codex")
        self.assertEqual(p.returncode, 0, p.stderr)

        self.assertFalse(os.path.lexists(self.link))
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(self.manifest_path.exists())
        for name in self.SKILL_NAMES:
            self.assertFalse(self._stub(name).exists(), name)
        for name in self.AGENT_NAMES:
            self.assertFalse((self.agents_dir / f"{name}.toml").exists(),
                             name)
        # hooks.json held only our entries -> the file we created is gone
        self.assertFalse(self.hooks_json.exists())
        # generated dirs are pruned when empty
        self.assertFalse((self.home / ".agents" / "skills").exists())
        self.assertFalse((self.home / ".codex" / "agents").exists())

    def test_uninstall_codex_restores_foreign_hooks(self):
        self.hooks_json.parent.mkdir(parents=True)
        self.hooks_json.write_text(json.dumps({"hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": "echo foreign"}]}]}}))
        self.assertEqual(self._install("--harness", "codex").returncode, 0)
        p = self._uninstall("codex")
        self.assertEqual(p.returncode, 0, p.stderr)
        cfg = json.loads(self.hooks_json.read_text())
        cmds = self._hook_commands(cfg)
        self.assertFalse(any("--harness codex" in c for c in cmds))
        self.assertIn("echo foreign", cmds)


class InstallOpenCodeTest(InstallCase):
    """`kinetic install --harness opencode` is file generation only: flat
    kntc-<name>.md skill stubs under ~/.config/opencode/skills, markdown
    agents under ~/.config/opencode/agents and the kinetic.ts plugin under
    ~/.config/opencode/plugins. OpenCode file-drops plugins (no config merge,
    no trust step) so nothing foreign is touched; the opencode CLI is not
    required on PATH."""

    USER_ONLY = {"ask", "doctor", "implement", "init", "run", "status"}
    SKILL_NAMES = {"ask", "doctor", "grill", "implement", "init", "retro",
                   "run", "ship", "spec", "status", "tdd", "tickets"}
    AGENT_NAMES = {"fix-reviewer", "implementer", "implementer-strong",
                   "integration-reviewer", "spec-reviewer",
                   "standards-reviewer"}

    def setUp(self):
        super().setUp()
        # the opencode installer reads skills/, agents/ and templates/ from
        # the clone
        shutil.copytree(ROOT / "skills", self.clone / "skills",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "agents", self.clone / "agents",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "templates", self.clone / "templates",
                        ignore=shutil.ignore_patterns("__pycache__"))

    @property
    def skills_dir(self):
        return self.home / ".config" / "opencode" / "skills"

    @property
    def agents_dir(self):
        return self.home / ".config" / "opencode" / "agents"

    @property
    def plugins_dir(self):
        return self.home / ".config" / "opencode" / "plugins"

    @property
    def plugin(self):
        return self.plugins_dir / "kinetic.ts"

    @property
    def manifest_path(self):
        return (self.home / ".config" / "kinetic"
                / "install-manifest-opencode.json")

    def _stub(self, name):
        return self.skills_dir / f"kntc-{name}.md"

    def test_install_writes_stubs_agents_plugin_and_state(self):
        p = self._install("--harness", "opencode")
        self.assertEqual(p.returncode, 0, p.stderr)

        self.assertTrue(self.link.is_symlink())
        settings = self._settings()
        self.assertEqual(settings["harness"], "opencode")
        self.assertEqual(settings["clone"], str(self.clone))

        # one flat kntc-<name>.md stub per skill
        for name in self.SKILL_NAMES:
            stub = self._stub(name)
            self.assertTrue(stub.is_file(), name)
            text = stub.read_text()
            self.assertIn(f"name: kntc-{name}", text)
            self.assertIn('description: "kinetic: ', text)
            self.assertIn(f"{self.clone}/skills/{name}/SKILL.md", text)
            if name in self.USER_ONLY:
                self.assertIn("disable-model-invocation: true", text, name)
            else:
                self.assertNotIn("disable-model-invocation", text, name)

        # markdown agents, one per agents/*.md, tier resolved to a model
        from kinetic import harness as _h
        std = _h.resolve_tier("opencode", "standard",
                              settings=self.settings_path)
        sst = _h.resolve_tier("opencode", "strong",
                              settings=self.settings_path)
        for name in self.AGENT_NAMES:
            agent = self.agents_dir / f"{name}.md"
            self.assertTrue(agent.is_file(), name)
            text = agent.read_text()
            self.assertIn("mode: subagent", text)
            self.assertIn("description:", text)
            self.assertIn("# ", text)  # the markdown body is the prompt
        impl = (self.agents_dir / "implementer.md").read_text()
        strong = (self.agents_dir / "implementer-strong.md").read_text()
        self.assertIn(f'model: "{std["model"]}"', impl)
        self.assertIn(f'model: "{sst["model"]}"', strong)
        # tools: allow-list -> permission denies for omitted groups:
        # reviewers have no edit tools, implementers do
        reviewer = (self.agents_dir / "spec-reviewer.md").read_text()
        self.assertIn("- action: edit", reviewer)
        self.assertIn("effect: deny", reviewer)
        self.assertNotIn("- action: edit", impl)
        self.assertIn("- action: webfetch", impl)  # no WebFetch in tools:

        # the plugin is generated with the clone path baked in
        self.assertTrue(self.plugin.is_file())
        text = self.plugin.read_text()
        self.assertIn(str(self.clone), text)
        for needle in ("--harness", "opencode", "execute.before",
                       "execute.after", "experimental.idle",
                       "permission", "completion_gate", "record_edit",
                       "isolation", "orient"):
            self.assertIn(needle, text)

        m = json.loads(self.manifest_path.read_text())
        self.assertEqual(m["harness"], "opencode")
        self.assertEqual(m["clone"], str(self.clone))
        # every generated file is manifest-listed for staleness checks
        for f in (self._stub("run"), self.agents_dir / "implementer.md",
                  self.plugin):
            self.assertIn(str(f), m["files"])
        self.assertIn("docs/smoke/opencode.md", p.stdout)

    def test_install_opencode_is_idempotent(self):
        self.assertEqual(self._install("--harness", "opencode").returncode, 0)
        first_manifest = self.manifest_path.read_text()
        first_plugin = self.plugin.read_text()
        p = self._install("--harness", "opencode")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.manifest_path.read_text(), first_manifest)
        self.assertEqual(self.plugin.read_text(), first_plugin)

    def test_install_opencode_preserves_foreign_plugins(self):
        foreign = self.plugins_dir / "rtk.ts"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("// foreign plugin\n")
        warp = self.plugins_dir / "opencode-warp"
        warp.mkdir()
        (warp / "index.ts").write_text("// foreign\n")
        p = self._install("--harness", "opencode")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(foreign.read_text(), "// foreign plugin\n")
        self.assertTrue((warp / "index.ts").is_file())

        p = self._uninstall("opencode")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(foreign.is_file())
        self.assertTrue((warp / "index.ts").is_file())

    def test_install_opencode_replaces_stale_clone_paths(self):
        self.assertEqual(self._install("--harness", "opencode").returncode, 0)
        moved = self.tmp / "clone2"
        shutil.copytree(self.clone, moved, symlinks=True)
        _git(moved, "init")
        p = self._install("--harness", "opencode", clone=moved)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(str(moved), self.plugin.read_text())
        # the baked path is a quoted JSON string, so the old clone path
        # cannot match as a substring of the new one (clone vs clone2)
        self.assertNotIn(json.dumps(str(self.clone)),
                         self.plugin.read_text())
        self.assertIn(str(moved), self._stub("run").read_text())
        # agent files carry no clone path but are regenerated regardless
        self.assertTrue((self.agents_dir / "implementer.md").is_file())

    def test_install_opencode_fails_without_skills(self):
        shutil.rmtree(self.clone / "skills")
        p = self._install("--harness", "opencode")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("skills", p.stderr)
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(self.plugin.exists())

    # --- uninstall ---------------------------------------------------------

    def test_uninstall_opencode_removes_everything_it_wrote(self):
        self.assertEqual(self._install("--harness", "opencode").returncode, 0)
        p = self._uninstall("opencode")
        self.assertEqual(p.returncode, 0, p.stderr)

        self.assertFalse(os.path.lexists(self.link))
        self.assertFalse(self.settings_path.exists())
        self.assertFalse(self.manifest_path.exists())
        for name in self.SKILL_NAMES:
            self.assertFalse(self._stub(name).exists(), name)
        for name in self.AGENT_NAMES:
            self.assertFalse((self.agents_dir / f"{name}.md").exists(),
                             name)
        self.assertFalse(self.plugin.exists())
        # generated dirs are pruned when empty; plugins dir stays (foreign
        # plugins may live there, and rmdir only fires on empty dirs anyway)
        self.assertFalse(self.skills_dir.exists())
        self.assertFalse(self.agents_dir.exists())


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
