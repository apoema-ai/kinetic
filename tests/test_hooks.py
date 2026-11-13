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

    def activate(self, granted=True):
        state.init(self.run_dir, "feature", "X-1")
        state.set_repo(self.run_dir, "api", str(self.repo), "main")
        if granted:
            state.record_gate(self.run_dir, "breakdown", True)
        ptr = self.home / ".config" / "kinetic"
        ptr.mkdir(parents=True)
        (ptr / "active-run").write_text(str(self.run_dir))

    def hook(self, name, payload, harness=None, env=None):
        """Run a hook as a subprocess. payload is a dict (JSON-encoded) or a raw
        stdin string; harness adds --harness <id>; env merges extra variables
        (e.g. DEVIN_PROJECT_DIR) over HOME=temp-home."""
        argv = [sys.executable, str(HOOKS / f"{name}.py")]
        if harness:
            argv += ["--harness", harness]
        merged = dict(os.environ, HOME=str(self.home))
        merged.update(env or {})
        data = payload if isinstance(payload, str) else json.dumps(payload)
        p = subprocess.run(argv, input=data, capture_output=True, text=True, env=merged)
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
        self.assertIn("kinetic verify", out["reason"])

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

    def test_isolation_denies_repo_before_breakdown_gate(self):
        self.activate(granted=False)
        out = self.hook("isolation", {"tool_name": "Write", "tool_input": {"file_path": str(self.repo / "a.py")}})
        self.assertEqual(self.decision(out), "deny")
        self.assertNotIn(str(self.repo) + ",", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_isolation_allows_run_dir_before_breakdown_gate(self):
        self.activate(granted=False)
        out = self.hook("isolation", {"tool_name": "Write", "tool_input": {"file_path": str(self.run_dir / "spec.md")}})
        self.assertIsNone(self.decision(out))

    def test_isolation_denies_run_worktrees_before_breakdown_gate(self):
        # the real layout: discover cuts worktrees inside the run directory
        self.activate(granted=False)
        wt = self.run_dir / "worktrees" / "api"
        state.set_repo(self.run_dir, "api", str(wt), "kinetic/X-1/integration")
        for path in (wt / "a.py", self.run_dir / "worktrees" / "api-T1" / "b.py"):
            out = self.hook("isolation", {"tool_name": "Write", "tool_input": {"file_path": str(path)}})
            self.assertEqual(self.decision(out), "deny", path)

    def test_isolation_keeps_grant_after_a_later_rejected_gate(self):
        self.activate()  # breakdown approved
        wt = self.run_dir / "worktrees" / "api"
        state.set_repo(self.run_dir, "api", str(wt), "kinetic/X-1/integration")
        state.record_gate(self.run_dir, "breakdown", False, "revise")
        out = self.hook("isolation", {"tool_name": "Write", "tool_input": {"file_path": str(wt / "a.py")}})
        self.assertIsNone(self.decision(out))

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


class DevinHooks(HookCase):
    """Devin CLI payloads as documented at docs.devin.ai/cli/extensibility/hooks:
    hook_event_name/prompt_id extras, session_id, no cwd (DEVIN_PROJECT_DIR env
    carries the project root), tool names exec/edit/write. Devin's PreToolUse
    output is a top-level {"decision": "block"|"approve", "reason"}; it has no
    "ask", so ask renders as the Claude-format hookSpecificOutput and Devin's
    own permission flow remains the prompt."""

    def devin(self, name, payload, cwd=None, **kw):
        # Always set DEVIN_PROJECT_DIR ("" when absent) so a value leaking in
        # from the developer's environment cannot change the result.
        env = {"DEVIN_PROJECT_DIR": str(cwd) if cwd is not None else ""}
        return self.hook(name, payload, harness="devin", env=env, **kw)

    def edit(self, path, **extra):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "edit",
                   "tool_input": {"file_path": path},
                   "session_id": "s1", "prompt_id": "p1"}
        payload.update(extra)
        return payload

    def exec_tool(self, cmd, sid="s1"):
        return {"hook_event_name": "PreToolUse", "tool_name": "exec",
                "tool_input": {"command": cmd, "shell_id": "main"},
                "session_id": sid, "prompt_id": "p1"}

    def test_isolation_denies_outside_in_devin_shape(self):
        self.activate()
        out = self.devin("isolation", self.edit("/etc/passwd"), cwd=self.repo)
        self.assertEqual(out["decision"], "block")
        self.assertIn("outside the run workspace", out["reason"])
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_isolation_allows_repo_and_project_dir_supplies_cwd(self):
        self.activate()
        self.assertIsNone(self.devin("isolation",
                                     self.edit(str(self.repo / "a.py")), cwd=self.repo))
        # relative path resolves against DEVIN_PROJECT_DIR, not the hook's cwd
        self.assertIsNone(self.devin("isolation", self.edit("sub/a.py"), cwd=self.repo))
        # without DEVIN_PROJECT_DIR a relative path falls back to os.getcwd()
        out = self.devin("isolation", self.edit("sub/a.py"))
        self.assertEqual(out["decision"], "block")

    def test_isolation_reads_path_alias(self):
        self.activate()
        p = self.edit("/etc/passwd")
        p["tool_input"] = {"path": "/etc/passwd"}
        out = self.devin("isolation", p, cwd=self.repo)
        self.assertEqual(out["decision"], "block")

    def test_exec_git_push_to_protected_branch_denied(self):
        self.activate()
        out = self.devin("confirm_write_ops", self.exec_tool("git push origin main"),
                         cwd=self.repo)
        self.assertEqual(out["decision"], "block")
        self.assertIn("protected branch", out["reason"])

    def test_exec_push_asks_without_top_level_decision(self):
        self.activate()
        out = self.devin("confirm_write_ops", self.exec_tool("git push origin feature"),
                         cwd=self.repo)
        self.assertIsNone(out.get("decision"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertIn("confirm with the user", out["hookSpecificOutput"]
                      ["permissionDecisionReason"])

    def test_exec_readonly_command_is_silent(self):
        self.activate()
        self.assertIsNone(self.devin("confirm_write_ops",
                                     self.exec_tool("git status"), cwd=self.repo))

    def test_fail_closed_asks_in_devin_shape(self):
        self.activate()
        (self.run_dir / "state.json").write_text("{not json")
        out = self.devin("isolation", self.edit("/etc/passwd"), cwd=self.repo)
        self.assertIsNone(out.get("decision"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertIn("could not decide", out["hookSpecificOutput"]
                      ["permissionDecisionReason"])

    def test_garbage_input_asks(self):
        out = self.devin("confirm_write_ops", "{bad", cwd=self.repo)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_claim_run_and_session_scope_via_exec(self):
        self.activate()
        self.devin("claim_run", {"hook_event_name": "PostToolUse", "tool_name": "exec",
                                 "tool_input": {"command": "printf '%s' /r | tee "
                                                      "~/.config/kinetic/active-run",
                                                "shell_id": "main"},
                                 "session_id": "s1", "prompt_id": "p1"}, cwd=self.repo)
        self.assertEqual(state.load(self.run_dir).get("owner_session"), "s1")
        # another session is out of scope (its cwd is the project dir, not the run dir)
        self.assertIsNone(self.devin("isolation", self.edit("/etc/passwd",
                                                            session_id="s2"),
                                     cwd=self.repo))
        out = self.devin("isolation", self.edit("/etc/passwd"), cwd=self.repo)
        self.assertEqual(out["decision"], "block")

    def test_record_edit_stamps_repo_for_write_tool(self):
        self.activate()
        self.devin("record_edit", {"hook_event_name": "PostToolUse", "tool_name": "write",
                                   "tool_input": {"file_path": str(self.repo / "a.py")},
                                   "tool_response": {"success": True, "output": "",
                                                     "error": None},
                                   "session_id": "s1", "prompt_id": "p1"}, cwd=self.repo)
        self.assertTrue(state.load(self.run_dir)["repos"]["api"]["last_edit_at"])

    # Devin's apply_patch payload shape is undocumented; the normalizer tries
    # the spellings the other harnesses use, with tool_input.command first.
    def patch(self, *sections):
        return "*** Begin Patch\n" + "".join(sections) + "*** End Patch"

    def update(self, path, body="@@\n-old\n+new\n"):
        return f"*** Update File: {path}\n{body}"

    def apply_patch(self, command=None, tool_input=None, event="PreToolUse"):
        ti = {"command": command} if tool_input is None else tool_input
        return {"hook_event_name": event, "tool_name": "apply_patch",
                "tool_input": ti, "session_id": "s1", "prompt_id": "p1"}

    def test_apply_patch_outside_is_denied(self):
        self.activate()
        out = self.devin("isolation",
                         self.apply_patch(self.patch(self.update("/etc/passwd"))),
                         cwd=self.repo)
        self.assertEqual(out["decision"], "block")
        self.assertIn("outside the run workspace", out["reason"])
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_apply_patch_inside_repo_run_dir_and_relative_allowed(self):
        self.activate()
        for path in (str(self.repo / "a.py"), str(self.run_dir / "spec.md"),
                     "sub/rel.py"):
            out = self.devin("isolation",
                             self.apply_patch(self.patch(self.update(path))),
                             cwd=self.repo)
            self.assertIsNone(out, path)

    def test_apply_patch_multi_file_any_outside_denies(self):
        self.activate()
        patch = self.patch(self.update(str(self.repo / "ok.py")),
                           self.update("/etc/evil.py"))
        out = self.devin("isolation", self.apply_patch(patch), cwd=self.repo)
        self.assertEqual(out["decision"], "block")
        self.assertIn("evil.py", out["reason"])

    def test_apply_patch_alternate_input_spelling(self):
        self.activate()
        out = self.devin("isolation",
                         self.apply_patch(tool_input={"patch": self.patch(
                             self.update("/etc/passwd"))}),
                         cwd=self.repo)
        self.assertEqual(out["decision"], "block")

    def test_apply_patch_unparseable_asks(self):
        self.activate()
        out = self.devin("isolation",
                         self.apply_patch("not a patch at all"), cwd=self.repo)
        self.assertIsNone(out.get("decision"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_apply_patch_record_edit_stamps_each_path(self):
        self.activate()
        patch = self.patch(self.update(str(self.repo / "a.py")),
                           self.update(str(self.run_dir / "notes.md")))
        self.devin("record_edit",
                   self.apply_patch(patch, event="PostToolUse"), cwd=self.repo)
        st = state.load(self.run_dir)
        self.assertTrue(st["repos"]["api"]["last_edit_at"])
        # run-dir artifacts are not code: the run_dir path must not stamp
        # the top-level last_edit_at
        self.assertFalse(st["last_edit_at"])

    def test_stop_gate_blocks_in_devin_shape(self):
        self.activate()
        self.stamp(repo_edit=T3)
        out = self.devin("completion_gate",
                         {"hook_event_name": "Stop", "stop_hook_active": False,
                          "session_id": "s1", "prompt_id": "p1",
                          "last_assistant_message": "done"}, cwd=self.home)
        self.assertEqual(out["decision"], "block")
        self.assertIn("kinetic verify", out["reason"])

    def test_orient_injects_context_for_session_start(self):
        self.activate()
        out = self.devin("orient", {"hook_event_name": "SessionStart",
                                    "source": "startup", "session_id": "s1"},
                         cwd=self.repo)
        out = out["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertIn("feature", out["additionalContext"])

    def test_unknown_harness_falls_back_to_claude(self):
        self.activate()
        out = self.hook("isolation", self.edit("/etc/passwd"), harness="bogus",
                        env={"DEVIN_PROJECT_DIR": ""})
        self.assertEqual(self.decision(out), "deny")

    def test_explicit_harness_claude_unchanged(self):
        self.activate()
        out = self.hook("isolation", {"tool_name": "Write",
                                      "tool_input": {"file_path": "/etc/passwd"}},
                        harness="claude")
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("hookSpecificOutput", out)


class CodexHooks(HookCase):
    """Codex CLI payloads: same Claude-compatible field names plus Codex
    extensions (hook_event_name, model, permission_mode, tool_use_id, turn_id,
    transcript_path). File edits arrive as tool_name "apply_patch" with the
    raw patch in tool_input.command (*** Begin Patch / *** Update File: ...);
    shell arrives as "Bash". Output is the same JSON shapes Claude uses:
    hookSpecificOutput.permissionDecision on PreToolUse, flat
    decision/reason on Stop, hookSpecificOutput.additionalContext on
    SessionStart. Verified against codex-cli hooks docs (learn.chatgpt.com)."""

    def codex(self, name, payload, **kw):
        return self.hook(name, payload, harness="codex", **kw)

    def pre(self, tool_name, tool_input, sid="s1", **extra):
        payload = {"hook_event_name": "PreToolUse", "session_id": sid,
                   "cwd": str(self.repo), "model": "gpt-6.1-sol",
                   "permission_mode": "default", "tool_name": tool_name,
                   "tool_input": tool_input, "tool_use_id": "tu1",
                   "turn_id": "t1", "transcript_path": None}
        payload.update(extra)
        return payload

    def patch(self, *sections):
        return "*** Begin Patch\n" + "".join(sections) + "*** End Patch"

    def update(self, path, body="@@\n-old\n+new\n"):
        return f"*** Update File: {path}\n{body}"

    def test_apply_patch_outside_is_denied(self):
        self.activate()
        out = self.codex("isolation", self.pre(
            "apply_patch", {"command": self.patch(self.update("/etc/passwd"))}))
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("outside the run workspace",
                      out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_apply_patch_inside_repo_and_run_dir_allowed(self):
        self.activate()
        for path in (str(self.repo / "a.py"), str(self.run_dir / "spec.md"),
                     "sub/rel.py"):
            out = self.codex("isolation", self.pre(
                "apply_patch", {"command": self.patch(self.update(path))}))
            self.assertIsNone(out, path)

    def test_apply_patch_multi_file_any_outside_denies(self):
        self.activate()
        patch = self.patch(self.update(str(self.repo / "ok.py")),
                           self.update("/etc/evil.py"))
        out = self.codex("isolation", self.pre("apply_patch",
                                               {"command": patch}))
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("evil.py",
                      out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_apply_patch_add_delete_and_move_headers_checked(self):
        self.activate()
        patch = self.patch(
            "*** Add File: /tmp/new.txt\n+hi\n",
            "*** Delete File: /etc/gone.txt\n",
            f"*** Update File: {self.repo}/moved.py\n@@\n-x\n"
            "*** Move to: /etc/stolen.py\n")
        out = self.codex("isolation", self.pre("apply_patch",
                                               {"command": patch}))
        self.assertEqual(self.decision(out), "deny")

    def test_apply_patch_record_edit_stamps_each_path(self):
        self.activate()
        patch = self.patch(self.update(str(self.repo / "a.py")),
                           self.update(str(self.run_dir / "notes.md")))
        self.codex("record_edit",
                   {"hook_event_name": "PostToolUse", "session_id": "s1",
                    "cwd": str(self.repo), "model": "gpt-6.1-sol",
                    "tool_name": "apply_patch",
                    "tool_input": {"command": patch},
                    "tool_response": "Success.", "tool_use_id": "tu1"})
        st = state.load(self.run_dir)
        self.assertTrue(st["repos"]["api"]["last_edit_at"])
        # run-dir artifacts are not code (R25): the run_dir path must not
        # stamp the top-level last_edit_at
        self.assertFalse(st["last_edit_at"])

    def test_bash_tool_confirm_write_ops_unchanged(self):
        self.activate()
        out = self.codex("confirm_write_ops", self.pre(
            "Bash", {"command": "git push origin main"}))
        self.assertEqual(self.decision(out), "deny")
        out = self.codex("confirm_write_ops", self.pre(
            "Bash", {"command": "git status"}))
        self.assertIsNone(out)

    def test_stop_gate_blocks_in_codex_shape(self):
        self.activate()
        self.stamp(repo_edit=T3)
        out = self.codex("completion_gate",
                         {"hook_event_name": "Stop", "session_id": "s1",
                          "cwd": str(self.repo), "model": "gpt-6.1-sol",
                          "permission_mode": "default",
                          "stop_hook_active": False, "turn_id": "t1",
                          "last_assistant_message": "done",
                          "transcript_path": None})
        self.assertEqual(out["decision"], "block")
        self.assertIn("kinetic verify", out["reason"])

    def test_orient_session_start_injects_context(self):
        self.activate()
        out = self.codex("orient",
                         {"hook_event_name": "SessionStart", "session_id": "s1",
                          "cwd": str(self.repo), "model": "gpt-6.1-sol",
                          "permission_mode": "default", "source": "startup",
                          "transcript_path": None})
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "SessionStart")
        self.assertIn("feature", hso["additionalContext"])

    def test_isolation_fail_closed_asks_on_apply_patch_garbage(self):
        self.activate()
        (self.run_dir / "state.json").write_text("{not json")
        out = self.codex("isolation", self.pre(
            "apply_patch", {"command": "not a patch at all"}))
        self.assertEqual(self.decision(out), "ask")

    def test_claim_run_via_bash_exec(self):
        self.activate()
        self.codex("claim_run",
                   {"hook_event_name": "PostToolUse", "session_id": "s1",
                    "cwd": str(self.repo), "model": "gpt-6.1-sol",
                    "tool_name": "Bash",
                    "tool_input": {"command":
                                   "printf '%s' /r | tee "
                                   "~/.config/kinetic/active-run"},
                    "tool_response": "", "tool_use_id": "tu1"})
        self.assertEqual(state.load(self.run_dir).get("owner_session"), "s1")


class OpenCodeHooks(HookCase):
    """Payloads as the generated OpenCode plugin forwards them: the raw
    tool.execute.before/after event fields (sessionID, agent, messageID, id,
    tool, input) plus kinetic_event and cwd. Tool inputs use OpenCode's own
    spellings — edit/write carry "path", patch carries patchText, shell
    carries "command"/"workdir". Pre-tool decisions render flat
    {"decision","reason"} (deny -> the plugin throws, ask -> permission
    evaluate); completion_gate keeps {"decision":"block"} and orient keeps
    hookSpecificOutput.additionalContext, both mapped by the plugin."""

    def oc(self, name, payload, **kw):
        return self.hook(name, payload, harness="opencode", **kw)

    def pre(self, tool, input_, sid="s1", **extra):
        payload = {"kinetic_event": "PreToolUse", "cwd": str(self.repo),
                   "sessionID": sid, "agent": "build", "messageID": "m1",
                   "id": "call1", "tool": tool, "input": input_}
        payload.update(extra)
        return payload

    def post(self, tool, input_, sid="s1", status="completed", **extra):
        payload = {"kinetic_event": "PostToolUse", "cwd": str(self.repo),
                   "sessionID": sid, "agent": "build", "messageID": "m1",
                   "id": "call1", "tool": tool, "input": input_,
                   "status": status}
        payload.update(extra)
        return payload

    def patch(self, *sections):
        return "*** Begin Patch\n" + "".join(sections) + "*** End Patch"

    def update(self, path, body="@@\n-old\n+new\n"):
        return f"*** Update File: {path}\n{body}"

    def decision(self, out):
        return out.get("decision") if out else None

    def test_edit_outside_is_denied_in_opencode_shape(self):
        self.activate()
        out = self.oc("isolation", self.pre("edit", {"path": "/etc/passwd"}))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("outside the run workspace", out["reason"])
        self.assertNotIn("hookSpecificOutput", out)

    def test_write_and_relative_path_use_session_cwd(self):
        self.activate()
        self.assertIsNone(self.oc("isolation",
                                  self.pre("write", {"path": "sub/a.py"})))
        out = self.oc("isolation", self.pre("write", {"path": "a.py"},
                                            cwd=str(self.home)))
        self.assertEqual(out["decision"], "deny")

    def test_patch_tool_extracts_file_paths(self):
        self.activate()
        out = self.oc("isolation", self.pre(
            "patch", {"patchText": self.patch(self.update("/etc/evil.py"))}))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("evil.py", out["reason"])
        # multi-file patch: any outside path denies
        patch = self.patch(self.update(str(self.repo / "ok.py")),
                           self.update("/etc/evil.py"))
        out = self.oc("isolation", self.pre("patch", {"patchText": patch}))
        self.assertEqual(out["decision"], "deny")
        # a patch inside the workspace is allowed
        patch = self.patch(self.update(str(self.repo / "a.py")))
        self.assertIsNone(self.oc("isolation",
                                  self.pre("patch", {"patchText": patch})))

    def test_patch_unparseable_asks(self):
        self.activate()
        out = self.oc("isolation",
                      self.pre("patch", {"patchText": "not a patch"}))
        self.assertEqual(out["decision"], "ask")

    def test_shell_maps_to_bash_for_confirm_write_ops(self):
        self.activate()
        out = self.oc("confirm_write_ops", self.pre(
            "shell", {"command": "git push origin main"}))
        self.assertEqual(out["decision"], "deny")
        self.assertIsNone(self.oc("confirm_write_ops", self.pre(
            "shell", {"command": "git status"})))
        # v1 spelled the shell tool "bash"; it maps the same way
        out = self.oc("confirm_write_ops", self.pre(
            "bash", {"command": "git push origin main"}))
        self.assertEqual(out["decision"], "deny")

    def test_mcp_namespaced_write_ops_ask(self):
        self.activate()
        for tool in ("github_create_pull_request",
                     "atlassian_create_issue"):
            out = self.oc("confirm_write_ops", self.pre(tool, {}))
            self.assertEqual(out["decision"], "ask", tool)

    def test_mcp_deploy_asks(self):
        self.activate()
        out = self.oc("confirm_deploy",
                      self.pre("tekton_trigger_deploy", {}))
        self.assertEqual(out["decision"], "ask")

    def test_record_edit_stamps_repo_for_write_and_patch(self):
        self.activate()
        self.oc("record_edit", self.post(
            "write", {"path": str(self.repo / "a.py")}))
        self.assertTrue(state.load(self.run_dir)["repos"]["api"]["last_edit_at"])
        self.oc("record_edit", self.post(
            "patch", {"patchText": self.patch(
                self.update(str(self.run_dir / "notes.md")))}))
        st = state.load(self.run_dir)
        self.assertTrue(st["repos"]["api"]["last_edit_at"])
        # run-dir artifacts are not code (R25)
        self.assertFalse(st["last_edit_at"])

    def test_failed_edit_is_not_recorded(self):
        self.activate()
        self.oc("record_edit", self.post(
            "write", {"path": str(self.repo / "a.py")}, status="error"))
        self.assertFalse(state.load(self.run_dir)["repos"]["api"]
                         .get("last_edit_at"))

    def test_claim_run_via_shell(self):
        self.activate()
        self.oc("claim_run", self.post(
            "shell", {"command": "printf '%s' /r | tee "
                                "~/.config/kinetic/active-run"}))
        self.assertEqual(state.load(self.run_dir).get("owner_session"), "s1")

    def test_session_scope_uses_sessionID(self):
        self.activate()
        self.oc("claim_run", self.post(
            "shell", {"command": "printf '%s' /r | tee "
                                "~/.config/kinetic/active-run"}, sid="s1"))
        # another session is out of scope unless its cwd is inside the run dir
        self.assertIsNone(self.oc("isolation", self.pre(
            "edit", {"path": "/etc/passwd"}, sid="s2", cwd=str(self.home))))
        out = self.oc("isolation", self.pre(
            "edit", {"path": "/etc/passwd"}, sid="s1"))
        self.assertEqual(out["decision"], "deny")

    def test_stop_gate_blocks_on_idle(self):
        self.activate()
        self.stamp(repo_edit=T3)
        out = self.oc("completion_gate",
                      {"kinetic_event": "Stop", "sessionID": "s1",
                       "cwd": str(self.repo), "stop_hook_active": False})
        self.assertEqual(out["decision"], "block")
        self.assertIn("kinetic verify", out["reason"])

    def test_orient_injects_context(self):
        self.activate()
        out = self.oc("orient", {"kinetic_event": "SessionStart",
                                 "sessionID": "s1"})
        hso = out["hookSpecificOutput"]
        self.assertIn("feature", hso["additionalContext"])

    def test_fail_closed_asks_in_opencode_shape(self):
        self.activate()
        (self.run_dir / "state.json").write_text("{not json")
        out = self.oc("isolation", self.pre("edit", {"path": "/etc/passwd"}))
        self.assertEqual(out["decision"], "ask")
        self.assertIn("could not decide", out["reason"])

    def test_garbage_input_asks(self):
        out = self.oc("confirm_write_ops", "{bad")
        self.assertEqual(out["decision"], "ask")


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

    def test_hooks_json_passes_harness_claude(self):
        cfg = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
        cmds = [h["command"] for ms in cfg.values() for m in ms for h in m["hooks"]]
        self.assertEqual(len(cmds), 7)
        for c in cmds:
            self.assertIn("--harness claude", c)


if __name__ == "__main__":
    unittest.main()
