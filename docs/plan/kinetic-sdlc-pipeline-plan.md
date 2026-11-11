# kinetic SDLC Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the kinetic Claude Code plugin: an idea/spec/ticket-to-linked-PRs pipeline with quick, feature and epic lanes.

**Architecture:** Deterministic Python scripts own all state (`state.json`) and graph logic; skills and subagents do judgment work and read script output; `/kinetic:run` is the only orchestrator; hooks enforce isolation, confirmations and the completion gate.

**Tech Stack:** Python 3.9+ stdlib only (`unittest`, `json`, `subprocess`, `pathlib`), bash, git, `gh`, Atlassian MCP. Claude Code plugin format.

**Spec:** [../specs/kinetic-sdlc-pipeline-design.md](../specs/kinetic-sdlc-pipeline-design.md)

## Global Constraints

- Unix-only (macOS, Linux). No Windows paths or `.cmd` wrappers.
- Scripts never call an LLM; LLM never parses raw script output (scripts emit JSON).
- No skill invokes another skill; no subagent dispatches a subagent; only commands orchestrate.
- Every skill and agent frontmatter has an explicit `model:` (`haiku`, `sonnet` or `opus`).
- Implementers: at most 3 concurrent; at most 1 running per repo.
- Edge types exactly: `snapshot`, `merge`, `release`. Jira labels: `edge:snapshot`, `edge:merge`, `edge:release`.
- Repo config: central `~/.config/kinetic/repos.json`, repo-root `.kinetic.json` wins key by key. Keys: `verify` (required), `publish_snapshot`, `pin`, `base_branch` (default `main`).
- Spec required sections (exact headings): `## Threat model`, `## Non-functional requirements`, `## Acceptance criteria`.
- Active-run pointer: `~/.config/kinetic/active-run` holds the absolute run dir; absent means no run.
- Plugin version starts `0.1.0`; bump patch on every change.
- Pocock skills are MIT (Copyright (c) 2026 Matt Pocock, confirmed by the user 2026-11-11). Copying is allowed; the full notice must ship in `THIRD_PARTY_LICENSES.md`.

## Review Focus

1. A ticket whose blocker is in another repo and edge `snapshot`, but the upstream never published a snapshot: frontier must not release it. (Task 4 test `test_snapshot_edge_waits_for_publish`.)
2. Session restarted mid-build with a ticket `running` and no report: state must not treat it as alive. (Task 2 test `test_stale_running_reported`.)
3. Edit after the last passing verify, then the agent stops claiming done: Stop hook must block. (Task 9 test `test_stop_blocks_when_edit_after_verify`.)
4. A repo with no `verify` in either config: doctor fails it and `verify.py` exits non-zero with a clear message instead of running nothing. (Task 5 test `test_missing_verify_command_errors`.)
5. Write to a path outside every active worktree while a run is active, including via `..` or a symlink: isolation hook denies. (Task 9 test `test_isolation_resolves_symlinks`.)

---

## File Structure

```
.claude-plugin/plugin.json
scripts/kinetic/__init__.py
scripts/kinetic/config.py        # repo config resolve
scripts/kinetic/state.py         # state.json CRUD + CLI
scripts/kinetic/graph.py         # ticket graph validation
scripts/kinetic/frontier.py      # ready set
scripts/kinetic/verify.py        # run verify command, record result
scripts/kinetic/detect_repos.py  # propose verify commands from marker files
scripts/kinetic/gitops.py        # merge, merge order, pin
scripts/kinetic/spec_lint.py
scripts/kinetic/status.py
scripts/kinetic/next_step.py
scripts/kinetic/doctor.py
hooks/hooks.json
hooks/record_edit.py  hooks/completion_gate.py  hooks/isolation.py
hooks/confirm_write_ops.py  hooks/confirm_deploy.py  hooks/orient.py
skills/{run,implement,init,doctor,status,ask}/SKILL.md     # commands (disable-model-invocation: true)
skills/run/guides/{lanes,gates,build-loop,recovery}.md
skills/{grill,spec,tickets,tdd,ship,retro}/SKILL.md        # adapted Pocock skills
agents/{implementer,standards-reviewer,spec-reviewer}.md
tests/test_*.py  tests/fixtures/two-repo/
README.md
```

Each script is importable (`from kinetic import state`) and runnable as `python3 -m kinetic.<name>` with `PYTHONPATH=scripts`; CLIs print JSON to stdout, errors to stderr, exit non-zero on failure.

---

### Task 1: Plugin scaffold and repo config

**Files:** Create `.claude-plugin/plugin.json`, `scripts/kinetic/__init__.py`, `scripts/kinetic/config.py`, `tests/test_config.py`.

**Interfaces:**
- Produces: `resolve(repo_name: str, repo_path: Path, central: Path = DEFAULT_CENTRAL) -> dict` with keys `verify`, `publish_snapshot`, `pin`, `base_branch`; raises `ConfigError` when `verify` missing. `DEFAULT_CENTRAL = Path.home()/".config/kinetic/repos.json"`.

- [ ] **Step 1: Write failing tests**
  - `test_repo_override_wins`: central `{"svc": {"verify": "make test", "base_branch": "master"}}`, repo `.kinetic.json` `{"verify": "mvn verify"}` → `{"verify": "mvn verify", "base_branch": "master", "publish_snapshot": None, "pin": None}`.
  - `test_default_base_branch_main`: only `verify` set → `base_branch == "main"`.
  - `test_missing_verify_raises`: neither file has `verify` → `ConfigError`.
- [ ] **Step 2:** `python3 -m unittest tests.test_config -v` → FAIL (import error).
- [ ] **Step 3:** Implement `resolve`; `plugin.json` = `{"name": "kinetic", "version": "0.1.0", "description": "SDLC pipeline: grill, spec, tickets, multi-repo build, review, ship, retro"}`.
- [ ] **Step 4:** Tests PASS.
- [ ] **Step 5:** Commit `feat: plugin scaffold and repo config`.

### Task 2: Run state

**Files:** Create `scripts/kinetic/state.py`, `tests/test_state.py`.

**Interfaces:**
- Consumes: none.
- Produces:
  - `init(run_dir: Path, lane: str, ref: str) -> dict`; lane in `{"quick","feature","epic"}`.
  - `load(run_dir) -> dict`, `save(run_dir, state) -> None` (atomic: write temp, `os.replace`).
  - `set_ticket(run_dir, ticket_id, **fields) -> dict`.
  - `record_verify(run_dir, ticket_id: str|None, exit_code: int, log_path: str) -> None` (stamps `at` = UTC ISO).
  - `record_edit(run_dir, path: str) -> None` (sets `last_edit_at`).
  - `record_gate(run_dir, gate: str, approved: bool, note: str = "") -> None`.
  - `add_ruling(run_dir, what: str, why: str, cost: str) -> None`.
  - `stale_running(state, reports_dir: Path) -> list[str]`: ticket ids `running` with no report file.
  - Schema: `{"run_id","lane","ref","phase","tickets":{id:{"repo","slice","status","blocked_by":[{"id","type"}],"branch","report"}},"gates":{},"rulings":[],"verify":{},"last_edit_at":null}`. Ticket status in `{"todo","running","done","done_with_concerns","needs_decision","blocked","merged","released"}`; `snapshot_published: bool` default false.
  - CLI subcommands mirroring each function.

- [ ] **Step 1: Failing tests:** `test_init_writes_schema` (keys above, `phase == "intake"`); `test_save_is_atomic` (no `.tmp` left; reload equals saved); `test_invalid_lane_rejected` (`ValueError`); `test_stale_running_reported` (ticket `T1` running, no `reports/T1.md` → `["T1"]`; with the file → `[]`); `test_record_verify_after_edit` (edit then verify → `verify[id]["at"] > last_edit_at`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: run state store`.

### Task 3: Ticket graph validation

**Files:** Create `scripts/kinetic/graph.py`, `tests/test_graph.py`.

**Interfaces:**
- Consumes: ticket dict shape from Task 2.
- Produces: `validate(tickets: dict, lane: str) -> list[str]` (empty = valid); `topo_order(tickets) -> list[str]`.

- [ ] **Step 1: Failing tests:** `test_cycle_detected` (A blocks B, B blocks A → error containing `"cycle"`); `test_child_without_repo`; `test_invalid_edge_type` (`"type": "soon"`); `test_unknown_blocker`; `test_slice_without_children` (a slice id referenced by no ticket, given `slices=["S1"]` key in input); `test_valid_epic_graph_empty`; `test_topo_order_blockers_first`.
- [ ] **Step 2–4:** Run FAIL, implement (Kahn's algorithm), PASS.
- [ ] **Step 5:** Commit `feat: ticket graph validation`.

### Task 4: Frontier

**Files:** Create `scripts/kinetic/frontier.py`, `tests/test_frontier.py`.

**Interfaces:**
- Consumes: `state.load`.
- Produces: `ready(state: dict, cap: int = 3) -> list[str]`, in `topo_order`.

Rules: ticket is ready when status `todo`; every blocker satisfies its edge: `snapshot` → blocker status in `{done,done_with_concerns,merged,released}` and `snapshot_published`; `merge` → blocker in `{merged,released}`; `release` → blocker `released`; its repo has no `running` ticket; total running + returned ≤ `cap`; at most one per repo in the returned list.

- [ ] **Step 1: Failing tests:** `test_snapshot_edge_waits_for_publish`; `test_snapshot_edge_ready_after_publish`; `test_merge_edge_needs_merged`; `test_release_edge_needs_released`; `test_one_per_repo`; `test_cap_counts_running` (2 running, cap 3 → at most 1 returned); `test_no_blockers_ready`.
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `feat: frontier`.

### Task 5: Verify and repo detection

**Files:** Create `scripts/kinetic/verify.py`, `scripts/kinetic/detect_repos.py`, `tests/test_verify.py`, `tests/test_detect.py`.

**Interfaces:**
- Consumes: `config.resolve`, `state.record_verify`.
- Produces: `run(run_dir: Path, ticket_id: str|None, repo_name: str, repo_path: Path) -> dict` → `{"exit_code": int, "log_path": str}`; log at `<run_dir>/logs/verify-<ticket|repo>-<ts>.log`. `propose(repo_path: Path) -> dict` → `{"verify": str|None, "marker": str|None}`.

Marker map (first match): `pom.xml` → `mvn -q verify`; `build.gradle` or `build.gradle.kts` → `./gradlew check`; `package.json` → `npm test`; `go.mod` → `go test ./...`; `Cargo.toml` → `cargo test`; `pyproject.toml` → `python -m pytest`; `Makefile` with a `test:` target → `make test`.

- [ ] **Step 1: Failing tests:** `test_records_exit_code` (verify `"true"` → 0 recorded; `"false"` → 1); `test_missing_verify_command_errors` (raises, message names the repo and both config paths); `test_propose_maven`; `test_propose_none` (empty dir → `verify is None`).
- [ ] **Step 2–4:** FAIL, implement (`subprocess.run(cmd, shell=True, cwd=repo_path)`, tee to log), PASS.
- [ ] **Step 5:** Commit `feat: verify gate and repo detection`.

### Task 6: Git operations

**Files:** Create `scripts/kinetic/gitops.py`, `tests/test_gitops.py` (tests build temp repos with `git init`).

**Interfaces:**
- Produces:
  - `create_worktree(bare_or_repo: Path, dest: Path, branch: str, base: str) -> None`.
  - `merge_ticket(repo_path: Path, ticket_branch: str, integration_branch: str) -> dict` → `{"merged": bool, "conflicts": list[str]}`; on conflict leaves the merge in progress for `resolving-merge-conflicts`.
  - `merge_order(state) -> list[str]` repos ordered so a repo comes after every repo it has a `merge` or `release` edge on; ties by name.
  - `pin(run_dir, upstream_repo, downstream_repo) -> dict` runs upstream `publish_snapshot` then downstream `pin` (env `KINETIC_UPSTREAM_REF`), sets upstream tickets `snapshot_published = True`; returns `{"ok": bool, "log_path": str}`; skips with `ok False` and reason when either command is unset.

- [ ] **Step 1: Failing tests:** `test_merge_clean`; `test_merge_conflict_lists_files`; `test_merge_order_respects_edges`; `test_pin_skips_without_commands`; `test_pin_marks_snapshot_published`.
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `feat: git operations`.

### Task 7: Spec lint, status, next step

**Files:** Create `scripts/kinetic/spec_lint.py`, `status.py`, `next_step.py`, tests for each.

**Interfaces:**
- `lint(markdown: str) -> list[str]` missing required headings (exact strings from Global Constraints) and empty sections.
- `render(state) -> str` Markdown: lane/phase line, ticket table (`id | repo | status | blocked by`), frontier list, gates.
- `suggest(state: dict|None) -> dict` → `{"command": str, "reason": str}`. Rules in order: no state → `/kinetic:run <ref>` "no active run"; any `needs_decision` → `/kinetic:run` "ticket <id> needs a decision"; stale running → `/kinetic:run` "recover <ids>"; phase `build` and frontier non-empty → `/kinetic:run` "N tickets ready"; phase `build`, frontier empty, all done → `/kinetic:run` "review and ship"; phase `ship` done → `/kinetic:run` "retro"; else `/kinetic:status`.

- [ ] **Step 1: Failing tests:** `test_lint_missing_threat_model`; `test_lint_empty_section`; `test_lint_clean`; `test_render_contains_ticket_rows`; one test per `suggest` rule.
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `feat: spec lint, status, next step`.

### Task 8: Doctor

**Files:** Create `scripts/kinetic/doctor.py`, `tests/test_doctor.py`.

**Interfaces:**
- `checks(repos: list[str]) -> list[dict]` each `{"name","status":"pass|warn|fail","fix": str}`. Checks: `git` and `gh` on PATH; `gh auth status` exit 0; central config parses; each repo resolves `verify`; skill presence (warn) for `superpowers`, `dev-fleet`, `find-ticket-repos`, `checkout-ticket-repos`, `resolving-merge-conflicts` by looking under `~/.claude/skills/<name>` and `~/.claude/plugins/cache/*/<plugin>/`. Atlassian MCP cannot be probed from a script: emit `warn` "check with /mcp".
- `main()` exits 1 if any `fail`.

- [ ] **Step 1: Failing tests** with a fake `PATH` and fake home: `test_missing_gh_fails`; `test_missing_skill_warns`; `test_repo_without_verify_fails`.
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `feat: doctor`.

### Task 9: Hooks

**Files:** Create `hooks/hooks.json`, `hooks/{record_edit,completion_gate,isolation,confirm_write_ops,confirm_deploy,orient}.py`, `tests/test_hooks.py` (feed JSON on stdin, assert stdout/exit).

**Interfaces:**
- Consumes: active-run pointer, `state.load`, `state.record_edit`.
- All hooks no-op (exit 0, no output) when no active run, except `confirm_write_ops` and `confirm_deploy`, which always apply.
- `record_edit` (PostToolUse `Write|Edit|MultiEdit`): `state.record_edit(file_path)`.
- `completion_gate` (Stop): if `last_edit_at` is newer than the newest `verify[*].at`, or that verify's `exit_code != 0`, output `{"decision": "block", "reason": "Run verify: no passing verify after the last edit."}`; also allow when `stop_hook_active` is true (avoid loops).
- `isolation` (PreToolUse `Write|Edit|MultiEdit|NotebookEdit`): resolve `os.path.realpath(file_path)`; allow if under any ticket worktree or the run dir; else `permissionDecision: "deny"` naming allowed roots.
- `confirm_write_ops` (PreToolUse `Bash` + `mcp__.*atlassian.*(create|edit|transition|addComment).*` + `mcp__.*github.*(create_pull_request|merge_pull_request|update_pull_request)`): for Bash, match `git push`, `gh pr (create|merge|edit|ready)`; return `permissionDecision: "ask"`. Deny `git push` targeting `master`, `main` of the base repo, or `Release*`.
- `confirm_deploy` (PreToolUse `mcp__.*deploy.*|mcp__.*tekton.*trigger.*`): `ask`.
- `orient` (SessionStart): with active run print ≤5 lines: run id, lane, phase, `suggest()` command and reason.

- [ ] **Step 1: Failing tests:** `test_stop_blocks_when_edit_after_verify`; `test_stop_allows_after_passing_verify`; `test_stop_respects_stop_hook_active`; `test_isolation_denies_outside`; `test_isolation_resolves_symlinks`; `test_isolation_noop_without_run`; `test_push_asks`; `test_push_to_master_denied`; `test_orient_silent_without_run`.
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `feat: hooks`.

### Task 10: Adapted skills

**Files:** Create `skills/{tdd,grill,spec,tickets,ship,retro}/SKILL.md` (+ `tdd/tests.md`, `tdd/mocking.md`), `THIRD_PARTY_LICENSES.md` (the MIT notice verbatim, plus superpowers' MIT notice if any of its text is copied). Source: `~/.agents/skills/<pocock-name>/`.

**Interfaces:**
- `grill` (model sonnet): from `grill-with-docs` + `grilling`; ground also covers threat model and NFRs; writes `GLOSSARY.md` and `docs/adr/`.
- `spec` (sonnet): from `to-spec`; output must contain the three required headings; runs `python3 -m kinetic.spec_lint <file>` and fixes until empty; publishes to Jira (issue in project from config) or `<run_dir>/spec.md`.
- `tickets` (sonnet; runs inline on the orchestrator's model, R29): from `to-tickets`; slice parent + per-repo children; edge labels; writes tickets into state via `kinetic.state set-ticket`; runs `kinetic.graph validate` until empty; local mode writes `<run_dir>/issues/NN-<repo>-<slug>.md`.
- `tdd` (sonnet): copy unchanged except remove the "call code-review" handoff (no skill-to-skill).
- `ship` (sonnet): from `pr`; uses `kinetic.gitops merge_order`; opens drafts with `gh pr create --draft` in order; links PRs in each body.
- `retro` (sonnet): from `retro`; adds runbook and release-notes drafts to `<run_dir>/docs/`.
- All: remove `disable-model-invocation`, remove any Skill-tool call to another skill, keep attribution line `Adapted from mattpocock/skills (<skill>)`.

- [ ] **Step 1:** Write `THIRD_PARTY_LICENSES.md`, then copy and edit each skill per the bullets.
- [ ] **Step 2:** `grep -L '^model:' skills/*/SKILL.md` → no output; `grep -l 'Skill tool' skills/{grill,spec,tickets,tdd,ship,retro}/SKILL.md` → no output.
- [ ] **Step 3:** Commit `feat: adapted pipeline skills`.

### Task 11: Subagents

**Files:** Create `agents/implementer.md`, `agents/standards-reviewer.md`, `agents/spec-reviewer.md`.

**Interfaces:**
- Brief (input, from `run`): `Run: <run_dir>`, `Ticket: <id>`, `Repo: <worktree>`, `Ticket file or Jira key`, `Report: <run_dir>/reports/<id>.md`, `Grant: <line>`.
- `implementer` (sonnet, `skills: [tdd]`): implements only in `Repo`; runs `python3 -m kinetic.verify --run <run_dir> --ticket <id> ...` before reporting; report's first line `Status: DONE|DONE_WITH_CONCERNS|NEEDS_DECISION|BLOCKED`, then `Branch:`, `Verify:` (log path), `Questions:`, `Concerns:`. Never pushes.
- Reviewers (opus): input diff ref `<integration>...<ticket-branch>`; output `<run_dir>/reviews/<id>-<axis>.md` with findings `severity | file:line | issue | fix`; read-only (tools: Read, Grep, Glob, Bash for `git diff` only).

- [ ] **Step 1:** Write the three files.
- [ ] **Step 2:** Every file has `model:`; implementer tools exclude `Agent`/`Task` (no subagent→subagent).
- [ ] **Step 3:** Commit `feat: subagents`.

### Task 12: Thin commands

**Files:** Create `skills/{init,doctor,status,ask,implement}/SKILL.md`, all `disable-model-invocation: true`, `argument-hint` set where they take args.

**Interfaces:**
- `init` (sonnet): runs `kinetic.detect_repos` over a repo list the user names, asks only about repos with `verify: null`, writes `~/.config/kinetic/repos.json` and tracker settings (`tracker: "jira"|"local"`, `jira_project`, `slice_issue_type`, `child_issue_type`), then runs doctor.
- `doctor` (haiku): runs `kinetic.doctor`, prints the table.
- `status` (haiku): runs `kinetic.status`.
- `ask` (haiku): prints lanes and entry-point table (spec section 3) plus `kinetic.next_step` output.
- `implement` (sonnet, `argument-hint: "<JIRA-KEY|ticket-file|spec-path>"`): checks the ref has acceptance criteria and a repo; else points to `/kinetic:run`; otherwise instructs the agent to follow `/kinetic:run` with `--from build`.

- [ ] **Step 1:** Write files.
- [ ] **Step 2:** `claude plugin validate .` passes.
- [ ] **Step 3:** Commit `feat: thin commands`.

### Task 13: The run orchestrator

**Files:** Create `skills/run/SKILL.md` (sonnet, `disable-model-invocation: true`, `argument-hint: "<JIRA-KEY|idea|spec-path> [--from build]"`), `skills/run/guides/{lanes,gates,build-loop,recovery}.md`.

**Interfaces:**
- Consumes every script CLI, the six skills (by instructing the agent to load them in sequence), the three agents, and by name: `find-ticket-repos`, `checkout-ticket-repos` (fallback `kinetic.gitops create_worktree`), `resolving-merge-conflicts`, `superpowers:receiving-code-review`, `dev-fleet:architecture-review <worktree> <base>`, `/security-review`, `dev-fleet:release` (optional).
- `lanes.md`: lane pick rules and the entry-point table.
- `gates.md`: three gates (spec, breakdown with the grant text from spec section 6, push/PR) and how each is recorded with `kinetic.state record-gate`.
- `build-loop.md`: the loop from spec section 5, step by step with the exact CLI calls; dispatch all frontier tickets in one message, `run_in_background: true`.
- `recovery.md`: on every entry run `state stale-running`; for each stale id check `git log` in its worktree and ask the user whether to re-dispatch. Never assume a prior-session agent is alive.
- Writes active-run pointer at start; removes it after retro.

- [ ] **Step 1:** Write the files.
- [ ] **Step 2:** `claude plugin validate .` passes; no guide references a file outside `skills/run/`.
- [ ] **Step 3:** Commit `feat: run orchestrator`.

### Task 14: End-to-end dry run and quality gate

**Files:** Create `tests/fixtures/two-repo/` (script that builds two temp git repos: `lib` with `verify: "true"`, `publish_snapshot: "true"`; `svc` with `verify: "true"`, `pin: "true"`), `tests/test_e2e_scripts.py`, `README.md`.

- [ ] **Step 1: Failing test** `test_epic_flow_scripts`: init epic state; add tickets `L1 (lib)`, `S1 (svc, blocked_by L1 snapshot)`; `graph.validate` empty; `frontier.ready == ["L1"]`; mark L1 done; `ready == []`; `pin(lib, svc)`; `ready == ["S1"]`; mark S1 done; `merge_order == ["lib","svc"]`; `next_step.suggest` → "review and ship".
- [ ] **Step 2–4:** FAIL, fix whatever is missing, PASS.
- [ ] **Step 5:** Full suite: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v` → all pass; report counts.
- [ ] **Step 6:** Run `claude-code-upgrade:skill-forge` on every skill and agent in `skills/` and `agents/`; fix findings.
- [ ] **Step 7:** Manual dry run: `claude --plugin-dir .`, `/kinetic:run "test idea"` in local-tracker mode against the fixture; confirm each gate stops and the Stop hook blocks an unverified "done".
- [ ] **Step 8:** README (install, `/kinetic:init`, lanes, commands); bump version to `0.1.1`; commit `feat: e2e dry run and docs`.

---

## Dependencies

- Wave 1 (parallel): Tasks 1–8 depend only on Task 1 and Task 2 interfaces (do 1, 2 first, then 3–8 in parallel); Task 9 after 2; Task 10 independent.
- Wave 2: Task 11 after 5.
- Wave 3: Task 12 after 7, 8; Task 13 after 3–11.
- Wave 4: Task 14 last.
