from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(ROOT / "scripts"))
from kinetic import state  # noqa: E402

T1 = "2026-01-01T00:00:00.000000+00:00"
T2 = "2026-01-01T00:00:01.000000+00:00"
T3 = "2026-01-01T00:00:02.000000+00:00"


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(os.path.realpath(self.tmp.name)) / "home"
        self.home.mkdir()
        self.run_dir = Path(os.path.realpath(self.tmp.name)) / "run"
        self.repo = Path(os.path.realpath(self.tmp.name)) / "repo"
        self.repo.mkdir()

    def activate(self):
        state.init(self.run_dir, "feature", "X-1")
        state.set_repo(self.run_dir, "api", str(self.repo), "main")
        ptr = self.home / ".config" / "kinetic"
        ptr.mkdir(parents=True)
        (ptr / "active-run").write_text(str(self.run_dir))

    def hook(self, name, payload):
        env = dict(os.environ, HOME=str(self.home))
        p = subprocess.run([sys.executable, str(HOOKS / f"{name}.py")], input=json.dumps(payload),
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def decision(self, out):
        return out["hookSpecificOutput"]["permissionDecision"] if out else None

    def stamp(self, repo_edit=None, top_edit=None, verifies=None):
        def fn(s):
            if repo_edit:
                s["repos"]["api"]["last_edit_at"] = repo_edit
            if top_edit:
                s["last_edit_at"] = top_edit
            s["verify"].update(verifies or {})
        state._mutate(self.run_dir, fn)


class StopGate(HookCase):
    def test_stop_blocks_when_edit_after_verify(self):
        self.activate()
        self.stamp(repo_edit=T3, verifies={"repo:api": {"exit_code": 0, "log_path": "l", "at": T1, "repo": "api"}})
        out = self.hook("completion_gate", {"stop_hook_active": False})
        self.assertEqual(out["decision"], "block")
        self.assertIn("api", out["reason"])
        self.assertIn("kinetic.verify", out["reason"])

    def test_stop_allows_after_passing_verify(self):
        self.activate()
        self.stamp(repo_edit=T1, verifies={"repo:api": {"exit_code": 0, "log_path": "l", "at": T2, "repo": "api"}})
        self.assertIsNone(self.hook("completion_gate", {}))

    def test_stop_blocks_on_failing_newest_verify(self):
        self.activate()
        self.stamp(repo_edit=T1, verifies={"repo:api": {"exit_code": 1, "log_path": "l", "at": T2, "repo": "api"}})
        self.assertEqual(self.hook("completion_gate", {})["decision"], "block")

    def test_stop_respects_stop_hook_active(self):
        self.activate()
        self.stamp(repo_edit=T3)
        self.assertIsNone(self.hook("completion_gate", {"stop_hook_active": True}))

    def test_stop_skips_repo_with_running_ticket(self):
        self.activate()
        state.set_ticket(self.run_dir, "T-1", repo="api", status="running")
        self.stamp(repo_edit=T3)
        self.assertIsNone(self.hook("completion_gate", {}))

    def test_stop_blocks_top_level_edit_without_verify(self):
        self.activate()
        self.stamp(top_edit=T3)
        self.assertEqual(self.hook("completion_gate", {})["decision"], "block")

    def test_stop_noop_without_run_or_stamps(self):
        self.assertIsNone(self.hook("completion_gate", {}))
        self.activate()
        self.assertIsNone(self.hook("completion_gate", {}))


class Isolation(HookCase):
    def test_isolation_denies_outside(self):
        self.activate()
        out = self.hook("isolation", {"tool_name": "Write", "tool_input": {"file_path": "/etc/passwd"}})
        self.assertEqual(self.decision(out), "deny")
        self.assertIn(str(self.repo), out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_isolation_allows_repo_run_dir_and_relative(self):
        self.activate()
        for payload in ({"file_path": str(self.repo / "a.py")}, {"file_path": str(self.run_dir / "x.md")},
                        {"file_path": "sub/a.py"}):
            out = self.hook("isolation", {"tool_input": payload, "cwd": str(self.repo)})
            self.assertIsNone(out, payload)

    def test_isolation_denies_prefix_sibling(self):
        self.activate()
        out = self.hook("isolation", {"tool_input": {"file_path": str(self.repo) + "-evil/a.py"}})
        self.assertEqual(self.decision(out), "deny")

    def test_isolation_resolves_symlinks(self):
        self.activate()
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.repo / "link").symlink_to(outside)
        out = self.hook("isolation", {"tool_input": {"file_path": str(self.repo / "link" / "f.txt")}})
        self.assertEqual(self.decision(out), "deny")

    def test_isolation_noop_without_run(self):
        self.assertIsNone(self.hook("isolation", {"tool_input": {"file_path": "/etc/passwd"}}))


class Confirm(HookCase):
    def bash(self, cmd):
        return self.decision(self.hook("confirm_write_ops", {"tool_name": "Bash", "tool_input": {"command": cmd}}))

    def test_push_asks(self):
        self.assertEqual(self.bash("git push origin feature/x"), "ask")

    def test_push_after_commit_chain_asks(self):
        self.assertEqual(self.bash("git commit -m x && git push"), "ask")

    def test_push_to_master_denied(self):
        for cmd in ("git push origin master", "git push origin HEAD:main", "git push --force origin main",
                    "git push origin HEAD:refs/heads/Release-1.2", "git push -f origin +main"):
            self.assertEqual(self.bash(cmd), "deny", cmd)

    def test_gh_pr_asks_and_plain_commands_pass(self):
        self.assertEqual(self.bash("gh pr create --title x"), "ask")
        self.assertEqual(self.bash("echo ok; gh pr merge 3"), "ask")
        self.assertIsNone(self.bash("git commit -m 'push fix'"))
        self.assertIsNone(self.bash("git status"))

    def test_mcp_write_asks(self):
        out = self.hook("confirm_write_ops", {"tool_name": "mcp__github__create_pull_request", "tool_input": {}})
        self.assertEqual(self.decision(out), "ask")

    def test_deploy_asks(self):
        self.assertEqual(self.decision(self.hook("confirm_deploy", {"tool_name": "mcp__x__deploy_service"})), "ask")

    def test_fail_closed_on_garbage_input(self):
        env = dict(os.environ, HOME=str(self.home))
        p = subprocess.run([sys.executable, str(HOOKS / "confirm_write_ops.py")], input="{bad",
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0)


class RecordEditAndOrient(HookCase):
    def test_record_edit_stamps_repo(self):
        self.activate()
        self.assertIsNone(self.hook("record_edit", {"tool_input": {"file_path": str(self.repo / "a.py")}}))
        self.assertTrue(state.load(self.run_dir)["repos"]["api"]["last_edit_at"])

    def test_record_edit_noop_without_run(self):
        self.assertIsNone(self.hook("record_edit", {"tool_input": {"file_path": "/x"}}))

    def test_orient_silent_without_run(self):
        self.assertIsNone(self.hook("orient", {}))

    def test_orient_prints_at_most_five_lines(self):
        self.activate()
        out = self.hook("orient", {})["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        text = out["additionalContext"]
        self.assertLessEqual(len(text.splitlines()), 5)
        self.assertIn("feature", text)
        self.assertIn("intake", text)
        self.assertIn("/kinetic:", text)

    def test_hooks_json_wires_every_script(self):
        cfg = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
        cmds = " ".join(h["command"] for ms in cfg.values() for m in ms for h in m["hooks"])
        for name in ("record_edit", "completion_gate", "isolation", "confirm_write_ops", "confirm_deploy", "orient"):
            self.assertIn(f"{name}.py", cmds)


if __name__ == "__main__":
    unittest.main()
