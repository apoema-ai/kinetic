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


class SessionScope(HookCase):
    def write(self, path, **extra):
        return self.decision(self.hook("isolation", dict(
            {"tool_name": "Write", "tool_input": {"file_path": path}}, **extra)))

    def claim(self, sid, cmd="printf '%s' /r | tee ~/.config/kinetic/active-run"):
        self.hook("claim_run", {"tool_name": "Bash", "tool_input": {"command": cmd}, "session_id": sid})

    def test_pointer_write_claims_run_for_that_session(self):
        self.activate()
        self.claim("s1")
        self.assertEqual(state.load(self.run_dir).get("owner_session"), "s1")
        self.claim("s2")  # a resume in a new session re-claims
        self.assertEqual(state.load(self.run_dir).get("owner_session"), "s2")

    def test_unrelated_bash_does_not_claim(self):
        self.activate()
        self.claim("s1", cmd="ls ~/.config/kinetic")
        self.assertNotIn("owner_session", state.load(self.run_dir))

    def test_owner_session_is_isolated_other_session_is_not(self):
        self.activate()
        self.claim("s1")
        outside = str(self.home / "elsewhere.txt")
        self.assertEqual(self.write(outside, session_id="s1"), "deny")
        self.assertIsNone(self.write(outside, session_id="s2", cwd=str(self.home)))

    def test_cwd_inside_run_dir_is_in_scope_for_any_session(self):
        self.activate()
        self.claim("s1")
        wt = self.run_dir / "worktrees" / "api-1"
        wt.mkdir(parents=True)
        self.assertEqual(self.write(str(self.home / "x.txt"), session_id="sub", cwd=str(wt)), "deny")

    def test_unclaimed_run_or_missing_session_id_stays_global(self):
        self.activate()
        outside = str(self.home / "x.txt")
        self.assertEqual(self.write(outside, session_id="s2"), "deny")
        self.claim("s1")
        self.assertEqual(self.write(outside), "deny")

    def test_other_session_stop_not_gated(self):
        self.activate()
        self.claim("s1")
        self.stamp(repo_edit=T3)
        self.assertIsNone(self.hook("completion_gate", {"session_id": "s2", "cwd": str(self.home)}))
        self.assertEqual(self.hook("completion_gate", {"session_id": "s1"})["decision"], "block")


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

    def test_stop_hint_names_ticket_worktree_for_ticket_edit(self):  # I1
        self.activate()
        wt = self.run_dir / "worktrees" / "api-T-1"
        wt.mkdir(parents=True)
        state.set_ticket(self.run_dir, "T-1", repo="api", status="done", worktree=str(wt))
        self.hook("record_edit", {"tool_input": {"file_path": str(wt / "a.py")}})
        out = self.hook("completion_gate", {})
        self.assertEqual(out["decision"], "block")
        self.assertIn(f"--repo-path {wt}", out["reason"])
        self.assertIn("--ticket T-1", out["reason"])
        self.hook("record_edit", {"tool_input": {"file_path": str(self.repo / "b.py")}})
        out = self.hook("completion_gate", {})
        self.assertIn(f"--repo-path {self.repo}", out["reason"])
        self.assertNotIn("--ticket", out["reason"])

    def test_stop_skips_repo_with_running_ticket(self):
        self.activate()
        state.set_ticket(self.run_dir, "T-1", repo="api", status="running")
        self.stamp(repo_edit=T3)
        self.assertIsNone(self.hook("completion_gate", {}))

    def test_stop_blocks_top_level_edit_without_verify(self):
        self.activate()
        self.stamp(top_edit=T3)
        self.assertEqual(self.hook("completion_gate", {})["decision"], "block")

    def test_stop_other_repos_verify_does_not_satisfy(self):
        self.activate()
        state.set_repo(self.run_dir, "web", str(self.repo) + "-web", "main")
        self.stamp(repo_edit=T1, verifies={"repo:web": {"exit_code": 0, "log_path": "l", "at": T3, "repo": "web"}})
        out = self.hook("completion_gate", {})
        self.assertEqual(out["decision"], "block")
        self.assertIn("--repo-name api", out["reason"])

    def test_stop_skips_needs_decision_and_blocked(self):
        self.activate()
        self.stamp(repo_edit=T3)
        for status in ("needs_decision", "blocked"):
            state.set_ticket(self.run_dir, "T-1", repo="api", status=status)
            self.assertIsNone(self.hook("completion_gate", {}), status)

    def test_stop_handles_repo_without_path(self):
        self.activate()
        state._mutate(self.run_dir, lambda s: s["repos"].__setitem__("ghost", {"last_edit_at": T3}))
        out = self.hook("completion_gate", {})
        self.assertEqual(out["decision"], "block")
        self.assertIn("ghost", out["reason"])

    def test_stop_ignores_run_dir_artifact_edit(self):
        self.activate()
        self.hook("record_edit", {"tool_input": {"file_path": str(self.run_dir / "spec.md")}})
        self.assertIsNone(self.hook("completion_gate", {}))

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

    def test_isolation_asks_on_corrupt_state(self):
        self.activate()
        (self.run_dir / "state.json").write_text("{not json")
        out = self.hook("isolation", {"tool_input": {"file_path": "/etc/passwd"}})
        self.assertEqual(self.decision(out), "ask")

    def test_isolation_asks_when_body_raises(self):
        self.activate()
        state._mutate(self.run_dir, lambda s: s["repos"].__setitem__("bad", {}))  # entry without path
        out = self.hook("isolation", {"tool_input": {"file_path": "/etc/passwd"}})
        self.assertEqual(self.decision(out), "ask")

    def test_isolation_noop_when_pointer_dir_has_no_state(self):
        ptr = self.home / ".config" / "kinetic"
        ptr.mkdir(parents=True)
        (ptr / "active-run").write_text(str(self.run_dir))
        self.assertIsNone(self.hook("isolation", {"tool_input": {"file_path": "/etc/passwd"}}))

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
        self.assertEqual(self.bash("git commit -m 'push fix'"), "ask")
        self.assertIsNone(self.bash("git commit -m 'fix typo'"))
        self.assertIsNone(self.bash("git status"))

    def test_push_bypass_forms_denied(self):
        for cmd in ("true & git push origin main", "(git push origin main)", "echo $(git push origin main)",
                    "sudo git push origin main", "env git push origin main", "command git push origin main",
                    "/usr/bin/git push origin main", "git -C '/a b' push origin main",
                    "git --git-dir /x/.git push origin main", "bash -c 'git push origin main'",
                    "git p origin main", "(cd repo && git push origin main)",
                    "git push --all", "git push --mirror origin"):
            self.assertEqual(self.bash(cmd), "deny", cmd)

    def test_push_variants_ask_and_alias_asks(self):
        self.assertEqual(self.bash("sudo git push origin feature"), "ask")
        self.assertEqual(self.bash("git p origin feature"), "ask")
        self.assertEqual(self.bash("bash -c 'gh pr merge 3'"), "ask")
        self.assertEqual(self.bash("git push origin x && git checkout main"), "ask")

    def test_newline_is_a_command_separator(self):  # C2
        self.assertEqual(self.bash("git push -u origin kinetic/r1/integration\n"
                                   "gh pr create --draft --base main --head kinetic/r1/integration"), "ask")
        self.assertEqual(self.bash("git push origin feature\ngit checkout main"), "ask")
        self.assertEqual(self.bash("git push origin main\ngit status"), "deny")

    def test_line_continuation_push_denied(self):  # N1
        self.assertEqual(self.bash("git push origin \\\nmain"), "deny")
        self.assertEqual(self.bash("git push origin \\\r\nmain"), "deny")
        self.assertEqual(self.bash("git push \\\n  origin feature"), "ask")

    def test_readonly_git_on_protected_names_not_denied(self):
        for cmd in ("git merge-base main HEAD", "git ls-remote origin main", "git cat-file -p main",
                    "git show-ref main", "git for-each-ref refs/heads/main", "git rm -r main",
                    "git describe --all"):
            self.assertIsNone(self.bash(cmd), cmd)

    def test_quote_split_command_word_denied(self):
        for cmd in ("gi''t push origin main", 'gi""t push origin main', "g\\it push origin main"):
            self.assertEqual(self.bash(cmd), "deny", cmd)
        for cmd in ('"gh" pr merge 3', "gh pr 'merge' 3"):
            self.assertEqual(self.bash(cmd), "ask", cmd)

    def mcp(self, name, **inp):
        return self.decision(self.hook("confirm_write_ops", {"tool_name": name, "tool_input": inp}))

    def test_mcp_names_and_branch_deny(self):
        self.assertEqual(self.mcp("mcp__plugin_atlassian_atlassian__addOrEditJiraIssueComment"), "ask")
        self.assertEqual(self.mcp("mcp__plugin_atlassian_atlassian__executeWrite"), "ask")
        self.assertEqual(self.mcp("mcp__github-server__push_files", branch="main"), "deny")
        self.assertEqual(self.mcp("mcp__github-server__create_or_update_file", branch="Release-2"), "deny")
        self.assertEqual(self.mcp("mcp__github-server__push_files", branch="feat/x"), "ask")
        self.assertEqual(self.mcp("mcp__github-server__push_files", branch="refs/heads/main"), "deny")  # M3

    def test_matchers_cover_real_tools(self):
        import re
        cfg = json.loads((HOOKS / "hooks.json").read_text())["hooks"]["PreToolUse"]
        m = [e["matcher"] for e in cfg if "confirm_write_ops" in e["hooks"][0]["command"]][0]
        for n in ("mcp__plugin_atlassian_atlassian__addOrEditJiraIssueComment",
                  "mcp__plugin_atlassian_atlassian__executeWrite",
                  "mcp__plugin_atlassian_atlassian__executeDestructive",
                  "mcp__github-server__push_files", "mcp__github-server__delete_file",
                  "mcp__github-server__update_pull_request_branch",
                  "mcp__github-server__create_pull_request_review", "Bash"):
            self.assertTrue(re.fullmatch(m, n), n)

    def test_import_failure_fails_closed(self):
        import shutil
        d = Path(self.tmp.name) / "bare" / "hooks"
        d.mkdir(parents=True)
        for f in HOOKS.glob("*.py"):
            shutil.copy(f, d / f.name)
        self.activate()
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["HOME"] = str(self.home)
        p = subprocess.run([sys.executable, str(d / "isolation.py")], capture_output=True, text=True, env=env,
                           input=json.dumps({"tool_input": {"file_path": "/etc/passwd"}}))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")

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
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")


class RecordEditAndOrient(HookCase):
    def test_record_edit_stamps_repo(self):
        self.activate()
        self.assertIsNone(self.hook("record_edit", {"tool_input": {"file_path": str(self.repo / "a.py")}}))
        self.assertTrue(state.load(self.run_dir)["repos"]["api"]["last_edit_at"])

    def test_record_edit_resolves_relative_against_cwd(self):
        self.activate()
        self.hook("record_edit", {"tool_input": {"file_path": "a.py"}, "cwd": str(self.repo)})
        self.assertTrue(state.load(self.run_dir)["repos"]["api"].get("last_edit_at"))

    def test_record_edit_notebook_and_matcher(self):
        self.activate()
        self.hook("record_edit", {"tool_input": {"notebook_path": str(self.repo / "n.ipynb")}})
        self.assertTrue(state.load(self.run_dir)["repos"]["api"].get("last_edit_at"))
        cfg = json.loads((HOOKS / "hooks.json").read_text())["hooks"]["PostToolUse"]
        self.assertIn("NotebookEdit", cfg[0]["matcher"])

    def test_orient_collapses_whitespace(self):
        self.activate()
        state.set_ticket(self.run_dir, "T\n1", repo="api", status="needs_decision")
        text = self.hook("orient", {})["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(len(text.splitlines()), 5)
        self.assertIn("ticket T 1 needs", text)

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
