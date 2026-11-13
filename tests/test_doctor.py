from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kinetic import doctor, harness, install

SKILLS = ["resolving-merge-conflicts"]
PLUGINS = ["superpowers", "dev-fleet"]


class DoctorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.central = self.tmp / "repos.json"
        self.settings = self.tmp / "settings.json"
        self.repo = self.tmp / "svc"
        self.repo.mkdir()
        (self.repo / ".kinetic.json").write_text(json.dumps({"verify": "true"}))
        self._stub("git", 0)
        self._stub("gh", 0)
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.bin)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stub(self, name, code, body=""):
        p = self.bin / name
        p.write_text(f"#!/bin/sh\n{body}\nexit {code}\n")
        p.chmod(0o755)

    def _install_all_skills(self):
        for s in SKILLS:
            d = self.home / ".claude/skills" / s
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("x")
        for p in PLUGINS:
            (self.home / ".claude/plugins/cache/mkt" / p).mkdir(parents=True)

    def _by_name(self, repos=None, harness_id=None):
        res = doctor.checks(repos if repos is not None else [("svc", str(self.repo))],
                            self.home, self.central, settings=self.settings,
                            harness_id=harness_id)
        return {c["name"]: c for c in res}

    def _write_settings(self, **cfg):
        self.settings.write_text(json.dumps(cfg))

    def _fake_clone(self, name="clone"):
        """A minimal clone dir: hooks/hooks.json plus a bin/kinetic launcher."""
        clone = self.tmp / name
        (clone / "hooks").mkdir(parents=True, exist_ok=True)
        (clone / "hooks" / "hooks.json").write_text("{}")
        (clone / "bin").mkdir(exist_ok=True)
        (clone / "bin" / "kinetic").write_text("#!/bin/sh\n")
        return clone

    def _launcher_link(self, clone):
        """home/.local/bin/kinetic -> <clone>/bin/kinetic, as install writes it."""
        link = self.home / ".local" / "bin" / "kinetic"
        link.parent.mkdir(parents=True, exist_ok=True)
        target = clone / "bin" / "kinetic"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
        return link, target

    @staticmethod
    def _link_entry(target):
        return {"type": "symlink", "target": str(target),
                "sha256": hashlib.sha256(str(target).encode()).hexdigest()}

    def _write_manifest(self, hid="claude", files=None, clone=None):
        cfgdir = self.home / ".config" / "kinetic"
        cfgdir.mkdir(parents=True, exist_ok=True)
        mpath = cfgdir / f"install-manifest-{hid}.json"
        manifest = {"version": 1, "harness": hid,
                    "clone": str(clone) if clone else "",
                    "files": files if files is not None else {}}
        mpath.write_text(json.dumps(manifest))
        return mpath

    def _main_json(self, *argv):
        out = io.StringIO()
        with mock.patch.object(doctor.config, "DEFAULT_CENTRAL", self.central), \
                mock.patch.object(doctor.tracker, "DEFAULT_SETTINGS", self.settings), \
                mock.patch.object(doctor.Path, "home", return_value=self.home), \
                contextlib.redirect_stdout(out):
            code = doctor.main(list(argv))
        return code, json.loads(out.getvalue())

    def test_missing_gh_fails(self):
        (self.bin / "gh").unlink()
        c = self._by_name()
        self.assertEqual(c["gh"]["status"], "fail")
        self.assertTrue(c["gh"]["fix"])
        self.assertNotIn("gh-auth", c)
        self.assertEqual(c["git"]["status"], "pass")

    def test_gh_auth_failure_fails(self):
        self._stub("gh", 1)
        c = self._by_name()
        self.assertEqual(c["gh"]["status"], "pass")
        self.assertEqual(c["gh-auth"]["status"], "fail")

    def test_gh_auth_scoped_to_github_com(self):
        self._stub("gh", 1, 'case "$*" in "auth status --hostname github.com") exit 0;; esac')
        self.assertEqual(self._by_name()["gh-auth"]["status"], "pass")

    def test_gh_auth_timeout_has_own_fix(self):
        self._stub("gh", 0, "while :; do :; done")
        with mock.patch.object(doctor, "GH_TIMEOUT", 0.2):
            c = self._by_name()
        self.assertEqual(c["gh-auth"]["status"], "fail")
        self.assertIn("timed out", c["gh-auth"]["fix"])

    def test_dropped_companions_are_not_checked(self):
        c = self._by_name()
        self.assertNotIn("skill:find-ticket-repos", c)
        self.assertNotIn("skill:checkout-ticket-repos", c)

    def test_missing_skill_warns(self):
        self._install_all_skills()
        c = self._by_name()
        for n in SKILLS + PLUGINS:
            self.assertEqual(c["skill:" + n]["status"], "pass", n)
        (self.home / ".claude/skills/resolving-merge-conflicts/SKILL.md").unlink()
        (self.home / ".claude/plugins/cache/mkt/dev-fleet").rmdir()
        c = self._by_name()
        self.assertEqual(c["skill:resolving-merge-conflicts"]["status"], "warn")
        self.assertEqual(c["skill:dev-fleet"]["status"], "warn")
        self.assertEqual(c["skill:superpowers"]["status"], "pass")

    def test_repo_without_verify_fails(self):
        (self.repo / ".kinetic.json").unlink()
        c = self._by_name()
        self.assertEqual(c["verify:svc"]["status"], "fail")
        self.assertIn("verify", c["verify:svc"]["fix"])

    def test_repo_with_verify_passes(self):
        c = self._by_name()
        self.assertEqual(c["verify:svc"]["status"], "pass")
        self.assertEqual(c["verify:svc"]["fix"], "")

    def test_central_config_states(self):
        self.assertEqual(self._by_name()["central-config"]["status"], "warn")
        self.central.write_text("{not json")
        self.assertEqual(self._by_name()["central-config"]["status"], "fail")
        self.central.write_text("[]")
        self.assertEqual(self._by_name()["central-config"]["status"], "fail")
        self.central.write_text("{}")
        self.assertEqual(self._by_name()["central-config"]["status"], "pass")

    def test_non_dict_repo_entry_fails_cleanly(self):
        (self.repo / ".kinetic.json").unlink()
        self.central.write_text('{"svc": "x"}')
        c = self._by_name()
        self.assertEqual(c["verify:svc"]["status"], "fail")
        out = io.StringIO()
        with mock.patch.object(doctor.config, "DEFAULT_CENTRAL", self.central), \
                mock.patch.object(doctor.tracker, "DEFAULT_SETTINGS", self.settings), \
                mock.patch.object(doctor.Path, "home", return_value=self.home), \
                contextlib.redirect_stdout(out):
            code = doctor.main(["--repo", f"svc={self.repo}"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_bad_central_fails_repo_checks(self):
        self.central.write_text("{bad")
        c = self._by_name()
        self.assertEqual(c["central-config"]["status"], "fail")
        self.assertEqual(c["verify:svc"]["fix"], "fix central-config first")

    def test_repo_path_missing(self):
        c = self._by_name([("svc", str(self.tmp / "nope"))])
        self.assertEqual(c["verify:svc"]["status"], "fail")
        self.assertEqual(c["verify:svc"]["fix"], f"repo path not found: {self.tmp / 'nope'}")

    def test_cli_success_path(self):
        self.central.write_text("{}")
        out = io.StringIO()
        with mock.patch.object(doctor.config, "DEFAULT_CENTRAL", self.central), \
                mock.patch.object(doctor.tracker, "DEFAULT_SETTINGS", self.settings), \
                mock.patch.object(doctor.Path, "home", return_value=self.home), \
                contextlib.redirect_stdout(out):
            code = doctor.main(["--repo", f"svc={self.repo}"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])

    def test_atlassian_warns_only_for_jira(self):
        self._write_settings(tracker="jira", jira_project="P", slice_issue_type="S",
                             child_issue_type="C")
        c = self._by_name()
        self.assertEqual(c["atlassian-mcp"]["status"], "warn")
        self.assertEqual(c["atlassian-mcp"]["fix"], "check with /mcp")
        self.assertEqual(c["tracker-access"]["status"], "warn")
        self.assertEqual(c["tracker-access"]["fix"], "check the MCP with /mcp")
        self._write_settings(tracker="local")
        self.assertNotIn("atlassian-mcp", self._by_name())

    def test_doctor_tracker_fail_on_unknown(self):
        self._write_settings(tracker="nope")
        c = self._by_name()
        self.assertEqual(c["tracker"]["status"], "fail")
        self.assertIn("unknown tracker", c["tracker"]["fix"])
        self.assertEqual(c["tracker-access"]["status"], "fail")
        self.assertEqual(c["tracker-access"]["fix"], "fix tracker settings first")

    def test_tracker_default_local_passes(self):
        c = self._by_name()
        self.assertEqual(c["tracker"]["status"], "pass")
        self.assertEqual(c["tracker-access"]["status"], "pass")
        self.assertEqual(c["pr-template"]["status"], "pass")

    def test_tracker_access_github_reuses_gh_auth(self):
        self._write_settings(tracker="github", tracker_settings={"github_repo": "o/r"})
        self.assertEqual(self._by_name()["tracker-access"]["status"], "pass")
        self._stub("gh", 1)
        c = self._by_name()
        self.assertEqual(c["tracker-access"]["status"], "fail")
        self.assertEqual(c["tracker-access"]["fix"], c["gh-auth"]["fix"])
        (self.bin / "gh").unlink()
        c = self._by_name()
        self.assertEqual(c["tracker-access"]["status"], "fail")
        self.assertEqual(c["tracker-access"]["fix"], "run: gh auth login")

    def test_doctor_pr_template_missing(self):
        self._write_settings(pr_template="nope.md")
        c = self._by_name()
        self.assertEqual(c["pr-template"]["status"], "fail")
        self.assertIn(str(self.tmp / "nope.md"), c["pr-template"]["fix"])

    def test_cli_exit_code_and_output(self):
        (self.repo / ".kinetic.json").unlink()
        out = io.StringIO()
        with mock.patch.object(doctor.config, "DEFAULT_CENTRAL", self.central), \
                mock.patch.object(doctor.tracker, "DEFAULT_SETTINGS", self.settings), \
                mock.patch.object(doctor.Path, "home", return_value=self.home), \
                contextlib.redirect_stdout(out):
            code = doctor.main(["--repo", f"svc={self.repo}"])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertIn("verify:svc", [c["name"] for c in data["checks"]])

    # --- per-harness checks (harness profile, install manifest, companions) ---

    def test_harness_recorded_warns_until_install(self):
        c = self._by_name()
        self.assertEqual(c["harness"]["status"], "warn")
        self.assertIn("kinetic install --harness claude", c["harness"]["fix"])
        # harness recorded but clone missing -> still warn, not fail: a dev
        # checkout or pre-install state is expected to be incomplete
        self._write_settings(harness="claude")
        c = self._by_name()
        self.assertEqual(c["harness"]["status"], "warn")
        clone = self._fake_clone()
        self._write_settings(harness="claude", clone=str(clone))
        c = self._by_name()
        self.assertEqual(c["harness"]["status"], "pass")

    def test_harness_invalid_value_fails(self):
        self._write_settings(harness="bogus")
        c = self._by_name()
        self.assertEqual(c["harness"]["status"], "fail")
        self.assertIn("unknown harness", c["harness"]["fix"])
        # harness-dependent checks are skipped; companions fall back to claude
        self.assertNotIn("install-manifest", c)
        self.assertNotIn("tier-mapping", c)
        self._install_all_skills()
        c = self._by_name()
        self.assertEqual(c["skill:resolving-merge-conflicts"]["status"], "pass")

    def test_install_manifest_freshness(self):
        c = self._by_name()
        self.assertEqual(c["install-manifest"]["status"], "warn")
        self.assertIn("kinetic install --harness claude",
                      c["install-manifest"]["fix"])

        clone = self._fake_clone()
        link, target = self._launcher_link(clone)
        self._write_manifest("claude", clone=clone,
                             files={str(link): self._link_entry(target)})
        c = self._by_name()
        self.assertEqual(c["install-manifest"]["status"], "pass")

        # a generated file whose content changed is stale
        link.unlink()
        link.symlink_to("/usr/bin/true")
        c = self._by_name()
        self.assertEqual(c["install-manifest"]["status"], "fail")
        self.assertIn("kinetic install --harness claude",
                      c["install-manifest"]["fix"])

        # a missing generated file is stale too
        link.unlink()
        c = self._by_name()
        self.assertEqual(c["install-manifest"]["status"], "fail")

    def test_install_manifest_malformed_fails(self):
        mpath = self._write_manifest("claude")
        mpath.write_text("{bad")
        self.assertEqual(self._by_name()["install-manifest"]["status"], "fail")
        mpath.write_text("[]")
        self.assertEqual(self._by_name()["install-manifest"]["status"], "fail")

    def test_hooks_registered_states(self):
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "warn")
        self.assertIn("kinetic install --harness claude",
                      c["hooks-registered"]["fix"])

        clone = self._fake_clone()
        (clone / "hooks" / "hooks.json").unlink()
        self._write_settings(harness="claude", clone=str(clone))
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")

        self._fake_clone()
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "pass")
        self.assertNotIn("hooks-trusted", c)

    def test_hooks_registered_missing_clone_fails(self):
        gone = self.tmp / "gone"
        self._write_settings(harness="claude", clone=str(gone))
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")
        self.assertIn("clone path missing", c["hooks-registered"]["fix"])

    def _codex_hooks_json(self, clone, foreign=None):
        """Write ~/.codex/hooks.json with kinetic's codex hook groups plus
        optional foreign entries, as `kinetic install --harness codex` does."""
        hooks_path = self.home / ".codex" / "hooks.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        groups = install.codex_hook_groups(clone)
        if foreign:
            for event, g in foreign.items():
                groups.setdefault(event, []).extend(g)
        hooks_path.write_text(json.dumps({"hooks": groups}))
        return hooks_path

    def _codex_trust_all(self, hooks_path, enabled=True):
        """Write ~/.codex/config.toml [hooks.state] entries trusting every
        kinetic hook in hooks_path, as Codex records them after /hooks."""
        cfg_path = self.home / ".codex" / "config.toml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for e in doctor.codex_trust_entries(hooks_path):
            lines.append(f'[hooks.state."{e["key"]}"]')
            lines.append(f'trusted_hash = "{e["hash"]}"')
            if not enabled:
                lines.append("enabled = false")
        cfg_path.write_text("\n".join(lines) + "\n")
        return cfg_path

    def test_codex_hooks_registered_and_trusted(self):
        clone = self._fake_clone("codex-clone")
        self._write_settings(harness="codex", clone=str(clone))
        c = self._by_name()
        # no hooks.json at all -> warn to install
        self.assertEqual(c["hooks-registered"]["status"], "warn")
        self.assertIn("kinetic install --harness codex",
                      c["hooks-registered"]["fix"])

        hooks_path = self._codex_hooks_json(clone)
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "pass")
        # registered but not yet trusted via /hooks -> fail (US7)
        self.assertEqual(c["hooks-trusted"]["status"], "fail")
        self.assertIn("/hooks", c["hooks-trusted"]["fix"])

        self._codex_trust_all(hooks_path)
        c = self._by_name()
        self.assertEqual(c["hooks-trusted"]["status"], "pass")

    def test_codex_hooks_trusted_modified_and_disabled_fail(self):
        clone = self._fake_clone("codex-clone")
        self._write_settings(harness="codex", clone=str(clone))
        hooks_path = self._codex_hooks_json(clone)

        # a trusted_hash that does not match the current definition -> fail
        cfg_path = self.home / ".codex" / "config.toml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        entries = doctor.codex_trust_entries(hooks_path)
        lines = []
        for e in entries:
            lines.append(f'[hooks.state."{e["key"]}"]')
            lines.append('trusted_hash = "sha256:00"')
        cfg_path.write_text("\n".join(lines) + "\n")
        c = self._by_name()
        self.assertEqual(c["hooks-trusted"]["status"], "fail")

        # trusted but disabled -> the hook will not run -> fail
        self._codex_trust_all(hooks_path, enabled=False)
        c = self._by_name()
        self.assertEqual(c["hooks-trusted"]["status"], "fail")

    def test_codex_manifest_file_entries_checked_for_staleness(self):
        clone = self._fake_clone("codex-clone")
        self._write_settings(harness="codex", clone=str(clone))
        gen = self.home / ".agents" / "skills" / "kntc-run" / "SKILL.md"
        gen.parent.mkdir(parents=True)
        gen.write_text("stub")
        import hashlib
        self._write_manifest(
            "codex", clone=clone,
            files={str(gen): {"type": "file",
                              "sha256": hashlib.sha256(b"stub").hexdigest()}})
        c = self._by_name()
        self.assertEqual(c["install-manifest"]["status"], "pass")
        gen.write_text("edited")
        c = self._by_name()
        self.assertEqual(c["install-manifest"]["status"], "fail")

    def test_codex_hooks_registered_missing_and_stale_clone(self):
        clone = self._fake_clone("codex-clone")
        self._write_settings(harness="codex", clone=str(clone))
        # hooks.json exists but holds only foreign entries
        hooks_path = self.home / ".codex" / "hooks.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(json.dumps({"hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": "echo foreign"}]}]}}))
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")
        self.assertIn("kinetic install --harness codex",
                      c["hooks-registered"]["fix"])

        # entries point at a different clone path -> treated as missing
        moved = self._fake_clone("codex-clone2")
        hooks_path.write_text(json.dumps(
            {"hooks": install.codex_hook_groups(moved)}))
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")

        # malformed hooks.json -> fail, not crash
        hooks_path.write_text("{bad")
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")

    def _opencode_plugin(self, clone):
        """Write ~/.config/opencode/plugins/kinetic.ts pointing at clone."""
        plugin = self.home / ".config" / "opencode" / "plugins" / "kinetic.ts"
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text(f'const CLONE = "{clone}"\n')
        return plugin

    def test_opencode_hooks_registered_checks_plugin(self):
        clone = self._fake_clone("oc-clone")
        self._write_settings(harness="opencode", clone=str(clone))
        c = self._by_name()
        # no plugin at all -> warn to install
        self.assertEqual(c["hooks-registered"]["status"], "warn")
        self.assertIn("kinetic install --harness opencode",
                      c["hooks-registered"]["fix"])

        plugin = self._opencode_plugin(clone)
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "pass")
        # OpenCode plugins load without a trust step
        self.assertEqual(c["hooks-trusted"]["status"], "na")

        # plugin baked path points at a different clone -> stale -> fail
        moved = self._fake_clone("oc-clone2")
        plugin.write_text(f'const CLONE = "{moved}"\n')
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")
        self.assertIn("kinetic install --harness opencode",
                      c["hooks-registered"]["fix"])

        # missing clone -> fail
        gone = self.tmp / "gone"
        self._write_settings(harness="opencode", clone=str(gone))
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")
        self.assertIn("clone path missing", c["hooks-registered"]["fix"])

    def test_opencode_manifest_plugin_file_checked_for_staleness(self):
        clone = self._fake_clone("oc-clone")
        self._write_settings(harness="opencode", clone=str(clone))
        plugin = self._opencode_plugin(clone)
        self._write_manifest(
            "opencode", clone=clone,
            files={str(plugin): {"type": "file",
                                 "sha256": hashlib.sha256(
                                     plugin.read_bytes()).hexdigest()}})
        c = self._by_name()
        self.assertEqual(c["install-manifest"]["status"], "pass")
        plugin.write_text("changed")
        c = self._by_name()
        self.assertEqual(c["install-manifest"]["status"], "fail")

    def test_tier_mapping_check(self):
        clone = self._fake_clone()
        self._write_settings(harness="claude", clone=str(clone))
        c = self._by_name()
        self.assertEqual(c["tier-mapping"]["status"], "pass")

        self._write_settings(harness="claude", clone=str(clone),
                             tiers={"claude": {"standard": {"model": 5}}})
        c = self._by_name()
        self.assertEqual(c["tier-mapping"]["status"], "fail")
        self.assertIn("tiers", c["tier-mapping"]["fix"])

        self._write_settings(harness="claude", clone=str(clone), tiers="nope")
        c = self._by_name()
        self.assertEqual(c["tier-mapping"]["status"], "fail")

        self._write_settings(
            harness="claude", clone=str(clone),
            tiers={"claude": {"strong": {"model": "opus-4.1", "effort": "high"}}})
        c = self._by_name()
        self.assertEqual(c["tier-mapping"]["status"], "pass")

    def test_companion_skills_use_active_harness_dirs(self):
        # skills under ~/.claude do not count when the harness is codex
        for s in SKILLS:
            d = self.home / ".claude/skills" / s
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("x")
        clone = self._fake_clone("codex-clone")
        self._write_settings(harness="codex", clone=str(clone))
        c = self._by_name()
        self.assertEqual(c["skill:resolving-merge-conflicts"]["status"], "warn")
        self.assertIn(".agents/skills", c["skill:resolving-merge-conflicts"]["fix"])

        for s in SKILLS:
            d = self.home / ".agents/skills" / s
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("x")
        c = self._by_name()
        for s in SKILLS:
            self.assertEqual(c["skill:" + s]["status"], "pass", s)

    def test_companion_skills_any_profile_dir(self):
        # devin reads two skill dirs; a skill in either one counts
        clone = self._fake_clone("devin-clone")
        self._write_settings(harness="devin", clone=str(clone))
        for i, s in enumerate(SKILLS):
            base = self.home / (".config/devin/skills" if i % 2 == 0
                                else ".agents/skills")
            d = base / s
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("x")
        c = self._by_name()
        for s in SKILLS:
            self.assertEqual(c["skill:" + s]["status"], "pass", s)
        # devin's profile allows plugin companions; the claude cache is the
        # only known plugin location until the Devin installer lands
        self.assertEqual(c["skill:superpowers"]["status"], "warn")

    def test_companion_skills_flat_files_opencode_only(self):
        # OpenCode discovers flat <name>.md skill files too (the layout its
        # installer uses for kntc- stubs); other harnesses need the
        # <name>/SKILL.md directory layout
        for hid, skill_root in (("opencode", ".config/opencode/skills"),
                                ("codex", ".agents/skills")):
            clone = self._fake_clone(hid + "-clone")
            self._write_settings(harness=hid, clone=str(clone))
            for s in SKILLS:
                f = self.home / skill_root / f"{s}.md"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("x")
            c = self._by_name()
            for s in SKILLS:
                expected = "pass" if hid == "opencode" else "warn"
                self.assertEqual(c["skill:" + s]["status"], expected,
                                 (hid, s))

    def test_plugin_companions_na_when_profile_disallows(self):
        for hid in ("codex", "opencode"):
            clone = self._fake_clone(hid + "-clone")
            self._write_settings(harness=hid, clone=str(clone))
            for p in PLUGINS:
                (self.home / ".claude/plugins/cache/mkt" / p).mkdir(
                    parents=True, exist_ok=True)
            c = self._by_name()
            for p in PLUGINS:
                self.assertEqual(c["skill:" + p]["status"], "na", (hid, p))
                self.assertEqual(c["skill:" + p]["fix"], "n/a, fallback used")

    def test_guarantee_table_in_doctor_output(self):
        code, data = self._main_json("--repo", f"svc={self.repo}")
        self.assertEqual(code, 0)
        self.assertEqual(data["harness"], "claude")
        levels = {g["name"]: g["level"] for g in data["guarantees"]}
        self.assertEqual(set(levels), set(harness.GUARANTEES))
        self.assertTrue(all(v == "enforced" for v in levels.values()))
        self.assertEqual(data["tiers"]["standard"]["model"], "sonnet")
        self.assertEqual(data["tiers"]["strong"]["model"], "opus")
        self.assertNotIn("clone", data)

    def test_guarantee_table_marks_instructed(self):
        clone = self._fake_clone("oc-clone")
        self._write_settings(harness="opencode", clone=str(clone))
        code, data = self._main_json("--repo", f"svc={self.repo}")
        self.assertEqual(data["harness"], "opencode")
        levels = {g["name"]: g["level"] for g in data["guarantees"]}
        self.assertEqual(levels["verify-before-stop"], "instructed")
        self.assertEqual(levels["workspace-isolation"], "enforced")
        self.assertEqual(data["clone"], str(clone))

    def test_harness_override_ignores_other_harness_install(self):
        # settings records a claude install; checking codex must not reuse
        # claude's clone for hooks-registered or report claude's manifest
        clone = self._fake_clone()
        self._write_settings(harness="claude", clone=str(clone))
        c = self._by_name(harness_id="codex")
        self.assertEqual(c["harness"]["status"], "warn")
        self.assertIn("claude", c["harness"]["fix"])
        self.assertIn("codex", c["harness"]["fix"])
        self.assertEqual(c["install-manifest"]["status"], "warn")
        self.assertIn("codex", c["install-manifest"]["fix"])
        self.assertEqual(c["hooks-registered"]["status"], "warn")
        self.assertEqual(c["skill:superpowers"]["status"], "na")

    def test_claude_checks_unchanged_with_full_install(self):
        self._install_all_skills()
        clone = self._fake_clone()
        link, target = self._launcher_link(clone)
        self._write_settings(harness="claude", clone=str(clone))
        self._write_manifest("claude", clone=clone,
                             files={str(link): self._link_entry(target)})
        c = self._by_name()
        for n in SKILLS + PLUGINS:
            self.assertEqual(c["skill:" + n]["status"], "pass", n)
        for n in ("git", "gh", "gh-auth", "central-config", "verify:svc",
                  "tracker", "tracker-access", "pr-template"):
            self.assertIn(n, c)
        for n in ("harness", "install-manifest", "hooks-registered",
                  "tier-mapping"):
            self.assertEqual(c[n]["status"], "pass", (n, c[n]))
        self.assertNotIn("hooks-trusted", c)
        # companion fix text keeps the claude skill dir
        (self.home / ".claude/skills/resolving-merge-conflicts/SKILL.md").unlink()
        c = self._by_name()
        self.assertIn("~/.claude/skills", c["skill:resolving-merge-conflicts"]["fix"])

    # --- devin harness checks ---

    def _write_devin_config(self, clone):
        """~/.config/devin/config.json as `kinetic install --harness devin`
        writes it: every kinetic hook command under the hooks key."""
        path = self.home / ".config" / "devin" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        hooks = {}
        for cmd in install.devin_hook_commands(clone):
            hooks.setdefault("PreToolUse", []).append(
                {"matcher": "", "hooks": [{"type": "command",
                                           "command": cmd, "timeout": 10}]})
        path.write_text(json.dumps({"hooks": hooks}))
        return path

    def test_devin_hooks_registered_checks_devin_config(self):
        clone = self._fake_clone("devin-clone")
        self._write_settings(harness="devin", clone=str(clone))
        c = self._by_name()
        # no Devin hook config yet -> warn, not fail
        self.assertEqual(c["hooks-registered"]["status"], "warn")
        self.assertIn("kinetic install --harness devin",
                      c["hooks-registered"]["fix"])

        self._write_devin_config(clone)
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "pass")
        # Devin plugin hooks are best-effort; trust can't be verified
        self.assertEqual(c["hooks-trusted"]["status"], "warn")

        # commands pointing at a different clone are stale
        other = self._fake_clone("other-clone")
        self._write_devin_config(other)
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")
        self.assertIn("kinetic install --harness devin",
                      c["hooks-registered"]["fix"])

    def test_devin_hooks_registered_malformed_config_fails(self):
        clone = self._fake_clone("devin-clone")
        self._write_settings(harness="devin", clone=str(clone))
        path = self.home / ".config" / "devin" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{bad")
        c = self._by_name()
        self.assertEqual(c["hooks-registered"]["status"], "fail")

    def test_devin_plugin_companions_use_devin_store(self):
        clone = self._fake_clone("devin-clone")
        self._write_settings(harness="devin", clone=str(clone))
        c = self._by_name()
        self.assertEqual(c["skill:superpowers"]["status"], "warn")
        self.assertIn("devin plugins install", c["skill:superpowers"]["fix"])

        # a resolved plugin in devin's lock.json counts as installed
        store = self.home / ".local" / "share" / "devin" / "cli" / "plugins"
        store.mkdir(parents=True)
        (store / "lock.json").write_text(json.dumps(
            {"resolved": [{"name": "superpowers"}]}))
        c = self._by_name()
        self.assertEqual(c["skill:superpowers"]["status"], "pass")
        self.assertEqual(c["skill:dev-fleet"]["status"], "warn")

        # a cached plugin manifest counts too
        mdir = store / "cache" / "github.com_acme_dev-fleet-abc" / "1.0.0"
        (mdir / ".claude-plugin").mkdir(parents=True)
        (mdir / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "dev-fleet"}))
        c = self._by_name()
        self.assertEqual(c["skill:dev-fleet"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
