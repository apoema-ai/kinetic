# Kinetic repo discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a kinetic run start without knowing its repos: a packaged `discover` phase finds them from sources the user approves, registers them and cuts their worktrees; `/kinetic:init` with no paths uses the current directory.

**Architecture:** Deterministic parts are Python stdlib scripts (`state.py` gains `discover` phase, `set-lane`, `remove-repo`; new `discover.py` with `settings`, `remember`, `scan`, `register`; `graph.validate` checks ticket repos against the run; `hooks/isolation.py` keeps repos read-only until the breakdown gate). Judgment lives in a new phase skill `skills/discover/SKILL.md`, wired into the orchestrator guides. The two unpackaged companions `find-ticket-repos` and `checkout-ticket-repos` are dropped.

**Tech Stack:** Python 3.9 stdlib only, `unittest`, markdown skills and guides.

**Spec:** [docs/specs/kinetic-repo-discovery-design.md](../specs/kinetic-repo-discovery-design.md). Read it before any task; section numbers below refer to it.

## Global Constraints

- Python 3.9 stdlib only; every script prints JSON on stdout, errors on stderr with exit 1 (same as `state.py`, `graph.py`).
- `kinetic <module>` finds modules by file stem (`scripts/kinetic/__main__.py`), so `scripts/kinetic/discover.py` is callable as `kinetic discover` with no registration.
- Config paths: `~/.config/kinetic/settings.json` and `~/.config/kinetic/repos.json` (`config.DEFAULT_CENTRAL`). Every function that touches them takes the path as a keyword argument defaulting to that location, so tests pass temp paths.
- New settings keys: `repo_roots` (list of absolute paths) and `github_orgs` (list of org names). Missing keys read as `[]`.
- `PHASES` order: `intake, grill, discover, spec, tickets, build, review, ship, retro, done`.
- Integration branch name stays `kinetic/<run-id>/integration`; integration worktree stays `<run_dir>/worktrees/<repo>`.
- Skill and guide text: no Claude-only tool names (`AskUserQuestion`, `SendMessage`, `run_in_background`), no concrete model names in bodies, frontmatter parses with `yaml.safe_load` (quote a `description` containing `: `). `discover` is not user-only: no `triggers:` key. `tests/test_skill_text.py` enforces these.
- Version: bump `.claude-plugin/plugin.json` from `0.3.1` to `0.4.0` in Task 1.
- Git:
  - Work on branch `kinetic-repo-discovery`, created from `main`. Task 1 commits the spec and this plan with its code.
  - Stage by explicit path only.
  - Commit messages: `kinetic-repo-discovery: <summary>`. No co-author trailer, no mention of Claude.
- Tests: full suite `PYTHONPATH=scripts python3 -m unittest discover -s tests` (baseline: 421 tests, OK, 1 skipped). One module: `PYTHONPATH=scripts python3 -m unittest tests.test_<name> -k <pattern>`.

## Review Focus

1. **`scan` on a root that does not exist, or with a child it cannot read:** skips it and returns the rest; never raises. Test `test_scan_skips_missing_root_and_unreadable_child` in Task 2.
2. **`remember` with `~/code/`, `~/code` and a symlink to it in one or several calls:** stored once, as one absolute real path. Test `test_remember_normalizes_and_dedupes` in Task 2.
3. **`register` or `remember` when the existing JSON file is malformed:** raises `config.ConfigError` and leaves the file byte-for-byte unchanged. Test `test_malformed_config_is_never_overwritten` in Task 2.
4. **A 0.3.x run already past the breakdown gate (`gates.breakdown.approved` true) when this ships:** writes inside its repos stay allowed. Covered by `HookCase.activate` recording the gate in Task 4, so every existing isolation test keeps proving it.
5. **`remove-repo` for a repo whose only ticket is already `merged`:** still refused, since its work is in the integration branch. Test `test_remove_repo_refused_while_any_ticket_names_it` in Task 1.

---

### Task 1: State: `discover` phase, `set-lane`, `remove-repo`

**Files:**
- Modify: `scripts/kinetic/state.py` (`PHASES` line 19; new functions after `set_repo`; CLI in `main`)
- Modify: `.claude-plugin/plugin.json` (version `0.4.0`)
- Add: `docs/specs/kinetic-repo-discovery-design.md`, `docs/plan/kinetic-repo-discovery-plan.md` (already written, commit them here)
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `state.PHASES` with `"discover"` after `"grill"`.
- Produces: `state.set_lane(run_dir, lane: str) -> dict` (saved state). Raises `ValueError` when `lane` not in `LANES`, or when moving into or out of `"quick"` (same lane is a no-op, `quick`→`quick` included).
- Produces: `state.remove_repo(run_dir, name: str) -> dict`. Raises `ValueError` when `name` is not in `state["repos"]`, or when any ticket has `repo == name` (any status).
- Produces: CLI `kinetic state set-lane --run <dir> --lane <lane>` and `kinetic state remove-repo --run <dir> --name <repo>`, printing the saved state like the other mutating subcommands.

- [ ] **Step 1: Create the branch**

```bash
git -C ~/workspace/lab/kinetic switch -c kinetic-repo-discovery main
```

The untracked spec and plan files come along.

- [ ] **Step 2: Write the failing tests** in `tests/test_state.py`:

```python
def test_discover_phase_sits_between_grill_and_spec(self):
    self.assertEqual(state.PHASES.index("discover"), state.PHASES.index("grill") + 1)
    self.assertEqual(state.PHASES.index("spec"), state.PHASES.index("discover") + 1)

def test_set_lane_moves_between_feature_and_epic_at_any_phase(self):
    state.init(self.run_dir, "feature", "X-1")
    state.set_phase(self.run_dir, "build")
    self.assertEqual(state.set_lane(self.run_dir, "epic")["lane"], "epic")
    self.assertEqual(state.set_lane(self.run_dir, "feature")["lane"], "feature")

def test_set_lane_refuses_quick_both_ways_and_invalid(self):
    state.init(self.run_dir, "feature", "X-1")
    with self.assertRaises(ValueError):
        state.set_lane(self.run_dir, "quick")
    with self.assertRaises(ValueError):
        state.set_lane(self.run_dir, "huge")
    state.init(self.run_dir, "quick", "X-1", force=True)
    with self.assertRaises(ValueError):
        state.set_lane(self.run_dir, "epic")
    self.assertEqual(state.set_lane(self.run_dir, "quick")["lane"], "quick")

def test_remove_repo_drops_unused_repo(self):
    state.init(self.run_dir, "epic", "X-1")
    state.set_repo(self.run_dir, "api", "/w/api", "kinetic/X-1/integration")
    self.assertNotIn("api", state.remove_repo(self.run_dir, "api")["repos"])

def test_remove_repo_refused_while_any_ticket_names_it(self):
    state.init(self.run_dir, "epic", "X-1")
    state.set_repo(self.run_dir, "api", "/w/api", "kinetic/X-1/integration")
    state.set_ticket(self.run_dir, "T1", repo="api", blocked_by=[], status="merged")
    with self.assertRaises(ValueError):
        state.remove_repo(self.run_dir, "api")
    with self.assertRaises(ValueError):
        state.remove_repo(self.run_dir, "web")
```

Adapt the `set_ticket` call to that function's real keyword form in `state.py` if it differs; the assertion is what matters. Add one CLI test that runs `state.main(["set-lane", "--run", str(self.run_dir), "--lane", "epic"])` and checks exit 0 and the saved lane.

- [ ] **Step 3: Run them to see them fail**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_state -k lane -k remove_repo -k discover_phase`
Expected: FAIL (`AttributeError: ... set_lane`, `discover` not in `PHASES`).

- [ ] **Step 4: Implement** `PHASES`, `set_lane`, `remove_repo` (both through `_mutate`) and the two CLI subcommands, following `set_repo`'s pattern. Bump `plugin.json` to `0.4.0`.

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests`
Expected: OK. If a test pinned the old `PHASES` tuple, update it to the new order.

- [ ] **Step 6: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/state.py tests/test_state.py .claude-plugin/plugin.json docs/specs/kinetic-repo-discovery-design.md docs/plan/kinetic-repo-discovery-plan.md
git -C ~/workspace/lab/kinetic commit -m "kinetic-repo-discovery: discover phase, set-lane and remove-repo in state"
```

---

### Task 2: `kinetic discover` script

**Files:**
- Create: `scripts/kinetic/discover.py`
- Test: `tests/test_discover.py` (new)

**Interfaces:**
- Consumes: `config._load(path) -> dict` (raises `config.ConfigError` on bad JSON) and `config.DEFAULT_CENTRAL`.
- Produces (all in `discover.py`; `SETTINGS = Path.home() / ".config/kinetic/settings.json"`):
  - `settings(path=SETTINGS) -> dict`: `{"repo_roots": [...], "github_orgs": [...]}`, `[]` for missing keys or file.
  - `remember(roots: list, orgs: list, path=SETTINGS) -> dict`: same shape as `settings`, after saving. Roots are `~`-expanded and real-pathed; a root that is not a directory raises `ValueError` and nothing is written. Deduped, first-seen order kept, every other key in the file preserved; file created (with parent dir) if missing.
  - `scan(roots: list, central=config.DEFAULT_CENTRAL) -> list`: each item `{"name", "path", "remote", "registered", "registered_as"}`. For each root: if it is inside a git work tree, the single item for its top level; otherwise one item per direct child that has a `.git` entry (file or dir). `name` is the directory basename, `path` its real path, `remote` is `remote.origin.url` or `None`, `registered`/`registered_as` from comparing real paths with each `repos.json` entry's `path`. Missing roots and unreadable children are skipped.
  - `register(name: str, path: str, verify: str, publish_snapshot=None, pin=None, central=config.DEFAULT_CENTRAL) -> dict`: the entry. Empty `verify` → `ValueError`. Name already registered with a different real path → `ValueError`. Same name and path → no-op, returns the existing entry unchanged. Other entries preserved.
  - CLI `main(argv=None) -> int`: subcommands `settings`; `remember [--root P]... [--org O]...`; `scan --root P [--root P]...`; `register --name --path --verify [--publish-snapshot] [--pin]`. JSON to stdout; `ValueError`/`ConfigError`/`OSError` to stderr, exit 1.
- Written JSON uses `indent=2` and a trailing newline.

- [ ] **Step 1: Write the failing tests** in `tests/test_discover.py` (temp dir per test; make repos with `git init -q`):

```python
def test_settings_missing_file_gives_empty_lists(self):
    self.assertEqual(discover.settings(path=self.tmp / "nope.json"),
                     {"repo_roots": [], "github_orgs": []})

def test_remember_creates_file_and_keeps_other_keys(self):
    s = self.tmp / "settings.json"
    s.write_text('{"tracker": "jira"}')
    discover.remember([str(self.root)], ["acme"], path=s)
    data = json.loads(s.read_text())
    self.assertEqual(data["tracker"], "jira")
    self.assertEqual(data["repo_roots"], [str(self.root)])
    self.assertEqual(data["github_orgs"], ["acme"])

def test_remember_normalizes_and_dedupes(self):
    link = self.tmp / "link"; link.symlink_to(self.root)
    s = self.tmp / "settings.json"
    discover.remember([str(self.root) + "/", str(link)], ["acme"], path=s)
    out = discover.remember([str(self.root)], ["acme"], path=s)
    self.assertEqual(out["repo_roots"], [os.path.realpath(self.root)])
    self.assertEqual(out["github_orgs"], ["acme"])

def test_remember_rejects_non_directory_root(self):
    with self.assertRaises(ValueError):
        discover.remember([str(self.tmp / "missing")], [], path=self.tmp / "s.json")
    self.assertFalse((self.tmp / "s.json").exists())

def test_scan_folder_of_repos_one_level_only(self):
    # root/api (repo), root/web (repo), root/notes (plain dir), root/group/deep (repo two levels down)
    names = sorted(r["name"] for r in discover.scan([str(self.root)], central=self.repos_json))
    self.assertEqual(names, ["api", "web"])

def test_scan_root_inside_a_repo_returns_its_top_level(self):
    out = discover.scan([str(self.root / "api" / "src")], central=self.repos_json)
    self.assertEqual([r["name"] for r in out], ["api"])

def test_scan_marks_registered_by_real_path(self):
    # repos.json registers "backend" at a symlink pointing to root/api
    api = next(r for r in discover.scan([str(self.root)], central=self.repos_json) if r["name"] == "api")
    self.assertEqual((api["registered"], api["registered_as"]), (True, "backend"))

def test_scan_skips_missing_root_and_unreadable_child(self):
    # chmod 000 on root/locked (a repo); a root that does not exist
    out = discover.scan([str(self.tmp / "missing"), str(self.root)], central=self.repos_json)
    self.assertNotIn("locked", [r["name"] for r in out])

def test_register_adds_entry_and_keeps_others(self): ...
def test_register_refuses_empty_verify(self): ...
def test_register_refuses_name_taken_by_other_path(self): ...
def test_register_same_name_and_path_is_noop(self): ...

def test_malformed_config_is_never_overwritten(self):
    for f, call in ((self.tmp / "s.json", lambda p: discover.remember([str(self.root)], [], path=p)),
                    (self.tmp / "r.json", lambda p: discover.register("api", str(self.root / "api"), "make test", central=p))):
        f.write_text("{not json")
        with self.assertRaises(config.ConfigError):
            call(f)
        self.assertEqual(f.read_text(), "{not json")

def test_cli_scan_prints_json(self):
    # discover.main(["scan", "--root", str(self.root)]) with stdout captured -> exit 0, list of dicts
```

Skip the unreadable-child part with `unittest.skipIf(os.geteuid() == 0, ...)`, since root can read anything.

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_discover`
Expected: FAIL (`ModuleNotFoundError: kinetic.discover`).

- [ ] **Step 3: Implement `scripts/kinetic/discover.py`** to the Interfaces block. Use `git -C <p> rev-parse --show-toplevel` for "inside a work tree" and `git -C <p> config --get remote.origin.url` for the remote. Read both files through `config._load` before writing, so bad JSON raises before anything is touched.

- [ ] **Step 4: Run the tests until they pass**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_discover`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/discover.py tests/test_discover.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-repo-discovery: discover script (settings, remember, scan, register)"
```

---

### Task 3: `graph validate` checks ticket repos against the run

**Files:**
- Modify: `scripts/kinetic/graph.py` (`validate` line 87, `main` line 133)
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces: `graph.validate(tickets: dict, lane: str, slices: list | None = None, repos: dict | None = None) -> list`. When `repos` is not `None`, each agent ticket whose `repo` is set and not a key of `repos` adds the error `f"ticket {i}: repo '{repo}' is not in the run; run discover for it"`. Human tickets and `repos=None` are not checked (existing callers unchanged).
- Produces: `graph.main` passes `s.get("repos", {})` as `repos`.

- [ ] **Step 1: Write the failing tests**

```python
def test_agent_ticket_repo_must_be_in_run(self):
    errors = graph.validate({"A": t(repo="web")}, "epic", repos={"api": {}})
    self.assertTrue(any("repo 'web' is not in the run" in e for e in errors))
    self.assertEqual(graph.validate({"A": t(repo="api")}, "epic", repos={"api": {}}), [])

def test_human_ticket_without_repo_is_not_checked_against_run(self):
    self.assertEqual(graph.validate({"H": t(repo=None, kind="human")}, "epic", repos={}), [])
```

Use the file's existing `t(...)` helper; extend it with `kind` if it lacks one.

- [ ] **Step 2: Run to see them fail.** Run: `PYTHONPATH=scripts python3 -m unittest tests.test_graph -k in_run`. Expected: FAIL (unexpected keyword `repos`).

- [ ] **Step 3: Implement** the parameter, the error and the `main` call.

- [ ] **Step 4: Run the full suite.** Expected: OK. Any test that drives `graph main` on a state with tickets but no registered repos gets the repos registered with `state.set_repo` in its fixture.

- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/graph.py tests/test_graph.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-repo-discovery: graph validate rejects tickets whose repo is not in the run"
```

---

### Task 4: Isolation hook keeps repos read-only until the breakdown gate

**Files:**
- Modify: `hooks/isolation.py` (roots, line 19)
- Test: `tests/test_hooks.py` (`HookCase.activate` and new tests next to `test_isolation_allows_repo_run_dir_and_relative`)

**Interfaces:**
- Consumes: `state.record_gate(run_dir, gate: str, approved: bool, note: str = "")`; gates live at `state["gates"][<gate>]["approved"]`.
- Produces: repo paths from `state["repos"]` count as allowed roots only when `st.get("gates", {}).get("breakdown", {}).get("approved")` is true; the run directory is always allowed. Every harness (Claude hooks.json, Devin, Codex, the OpenCode plugin) runs this same `isolation.py`, so no other file changes.

- [ ] **Step 1: Update the fixture.** In `HookCase.activate`, after `set_repo`, add `state.record_gate(self.run_dir, "breakdown", True)`, so every existing isolation test keeps describing a run past the gate.

- [ ] **Step 2: Write the failing tests**

```python
def test_isolation_denies_repo_before_breakdown_gate(self):
    self.activate()
    state.record_gate(self.run_dir, "breakdown", False)
    out = self.hook("isolation", {"tool_name": "Write", "tool_input": {"file_path": str(self.repo / "a.py")}})
    self.assertEqual(self.decision(out), "deny")

def test_isolation_allows_run_dir_before_breakdown_gate(self):
    self.activate()
    state.record_gate(self.run_dir, "breakdown", False)
    out = self.hook("isolation", {"tool_name": "Write", "tool_input": {"file_path": str(self.run_dir / "spec.md")}})
    self.assertIsNone(self.decision(out))
```

- [ ] **Step 3: Run to see the first fail.** Run: `PYTHONPATH=scripts python3 -m unittest tests.test_hooks -k isolation`. Expected: `test_isolation_denies_repo_before_breakdown_gate` FAILS (got no decision).

- [ ] **Step 4: Implement** the gate condition in `isolation.py`. The deny message lists the allowed roots it actually used.

- [ ] **Step 5: Run the full suite.** Expected: OK. A test class with its own `activate` that relies on repo writes gets the same `record_gate` line.

- [ ] **Step 6: Commit**

```bash
git -C ~/workspace/lab/kinetic add hooks/isolation.py tests/test_hooks.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-repo-discovery: repos stay read-only until the breakdown gate"
```

---

### Task 5: Drop the two companions; install `discover`

**Files:**
- Modify: `scripts/kinetic/doctor.py:15` (`SKILLS = ["resolving-merge-conflicts"]`)
- Modify: `tests/test_doctor.py` (lines 15, 134-137, 279, 531-532, 642-644: retarget those assertions to `resolving-merge-conflicts`; add a test that `skill:find-ticket-repos` and `skill:checkout-ticket-repos` are absent from the checks)
- Modify: `tests/test_install.py` (both `SKILL_NAMES` sets, lines 424 and 690, gain `"discover"`)

**Interfaces:**
- Consumes: nothing new. The installers already glob `skills/*/SKILL.md`; `discover` is installed once Task 6 adds the file.

- [ ] **Step 1: Write the failing test** `test_dropped_companions_are_not_checked` in `tests/test_doctor.py`, asserting neither key appears in the check results. Add `"discover"` to both `SKILL_NAMES`.

- [ ] **Step 2: Run.** Run: `PYTHONPATH=scripts python3 -m unittest tests.test_doctor tests.test_install`. Expected: FAIL. The doctor test fails because the keys are still there. The install tests fail because `skills/discover/` does not exist yet.

- [ ] **Step 3: Implement** the `SKILLS` change and retarget the old doctor assertions.

- [ ] **Step 4: Run `tests.test_doctor`.** Expected: OK. `tests.test_install` stays red until Task 6. Commit only the doctor files now.

- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/doctor.py tests/test_doctor.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-repo-discovery: doctor no longer checks find-ticket-repos and checkout-ticket-repos"
```

The `test_install.py` change is committed in Task 6.

---

### Task 6: The `discover` phase skill

**Files:**
- Create: `skills/discover/SKILL.md`
- Modify: `tests/test_install.py` (the `SKILL_NAMES` edit from Task 5)

**Interfaces:**
- Consumes: `kinetic discover settings|remember|scan|register` (Task 2), `kinetic detect_repos`, `kinetic state set-lane|set-repo|add-ruling` (Task 1), `kinetic gitops worktree`, `config.resolve` for `base_branch` (default `main`).
- Produces: the skill the orchestrator reads at the `discover` phase, with input `Run: <run_dir>`, the ref, the candidates (each with where it came from), the spec location if any, and `Mode: full | confirm-only`. Output artifact: `<run_dir>/discovery.md`.

- [ ] **Step 1: Write `skills/discover/SKILL.md`.** Frontmatter: `name: discover`, a `description` (quoted), `model: sonnet`, no `triggers`. Body: spec §2 steps 1–7 and §3 confirm-only mode, as instructions:
  - Mark each step **you** (the user answers; never answer for them) or **agent** (no questions).
  - Step 3 is one message with all three questions through "the harness's question tool".
  - The confidence levels and the "not enough" rule are copied exactly from spec §2 steps 4–5. At most two follow-up rounds.
  - The confirm message has two groups, Candidates and Suspected, unconfirmed. Repos are always named, never shown only as a path.
  - Clone consent: one question for every repo that exists only on GitHub. "Clone them into <first repo_root>" is the recommended answer.
  - Config is written only through `kinetic discover remember|register`, never with the edit tools (spec §6).
  - The ruling and `discovery.md` contents are as in spec §2 step 7.5.
  - Rules: this skill never invokes another skill; reading sources sends nothing off the machine.

- [ ] **Step 2: Run the text and install tests**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_skill_text tests.test_install`
Expected: OK. If `test_skill_text` flags a name or model, reword it.

- [ ] **Step 3: Commit**

```bash
git -C ~/workspace/lab/kinetic add skills/discover/SKILL.md tests/test_install.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-repo-discovery: discover phase skill"
```

---

### Task 7: Wire discover into the orchestrator, tickets and init

**Files:**
- Modify: `skills/run/SKILL.md`: phase order line, a `discover` row in the phases table ("Read and follow `skills/discover/SKILL.md`"), and the `tickets` row loses `find-ticket-repos`.
- Modify: `skills/run/guides/lanes.md`: "Pick the lane" per spec §1 (lane at intake only when the repo is known; otherwise provisional `feature`, final lane set by discover with `set-lane`). Entry-point table: "Spec, no tickets → discover"; tickets in hand and `--from build` → discover confirm-only, then build. Quick-lane order: intake, discover confirm-only, breakdown gate, build.
- Modify: `skills/run/guides/build-loop.md`: setup step 3 per spec §5. Worktrees already exist. A ticket repo not in the run sends the run back to tickets and re-asks the breakdown gate. Still recreate a missing worktree for a repo in state. Remove `checkout-ticket-repos`. Also add: a run with empty `state.repos` at the breakdown gate or build setup runs discover confirm-only first (spec Compatibility).
- Modify: `skills/run/guides/gates.md`: the breakdown gate lists the run's repos.
- Modify: `skills/tickets/SKILL.md`: a ticket's `repo` must be in the run. When another repo is needed, say so, and the orchestrator runs discover confirm-only without changing phase. Explore code in `state.repos[<repo>].path`. Run `kinetic graph validate`, which now enforces this.
- Modify: `skills/run/guides/recovery.md`: a run in `discover` resumes from `<run_dir>/discovery.md` and `state.repos`; a repo dropped by a later pass is removed with `state remove-repo` plus `git worktree remove`.
- Modify: `skills/init/SKILL.md`: step 1 with no arguments runs `kinetic discover scan --root "$PWD"`, then follows spec §7. When it's a folder of repos, also offer `kinetic discover remember --root "$PWD"`.

**Interfaces:**
- Consumes: Tasks 1–6.

- [ ] **Step 1: Make the edits above.** Keep each guide's existing style. Name scripts as `kinetic <module> ...`.

- [ ] **Step 2: Check that no stale references remain**

Run: `git -C ~/workspace/lab/kinetic grep -n "find-ticket-repos\|checkout-ticket-repos" -- skills agents trackers templates`
Expected: no output.

- [ ] **Step 3: Run the full suite.** Expected: OK.

- [ ] **Step 4: Commit**

```bash
git -C ~/workspace/lab/kinetic add skills/run skills/tickets/SKILL.md skills/init/SKILL.md
git -C ~/workspace/lab/kinetic commit -m "kinetic-repo-discovery: run, lanes, build loop, tickets and init use the discover phase"
```

---

### Task 8: README and glossary

**Files:**
- Modify: `README.md`
  - Quick start step 1: init with no paths.
  - "How a run flows": add `[discover]` after `[grill]`, with the line "candidate repos, approved sources, worktrees".
  - "Lanes and entry points": per spec §1.
  - Epic example: intake doesn't know the repos; discover asks once, finds `statement-client` through a code hit on `StatementClient.export`, and you confirm.
  - "Branches and worktrees": integration worktrees are cut at discover.
  - Line 90: drop the two companions.
  - Configuration: `repo_roots` and `github_orgs` in `settings.json`.
  - Skills table: a `discover` row (phase skill, inline).
- Modify: `GLOSSARY.md`: add **Repo root** and **Discovery** with their *Avoid* lines (spec §9).

- [ ] **Step 1: Make the edits.**

- [ ] **Step 2: Check for stale text**

Run: `git -C ~/workspace/lab/kinetic grep -n "find-ticket-repos\|checkout-ticket-repos\|repo detection first" -- README.md GLOSSARY.md`
Expected: no output.

- [ ] **Step 3: Run the full suite.** Expected: OK (`test_templates` and `test_skill_text` read docs).

- [ ] **Step 4: Commit**

```bash
git -C ~/workspace/lab/kinetic add README.md GLOSSARY.md
git -C ~/workspace/lab/kinetic commit -m "kinetic-repo-discovery: document the discover phase, repo roots and init from the current directory"
```

---

## Not covered by tests

The skill text (discover steps 1–7, init's current-directory flow, the orchestrator wiring) is Instructed, not Enforced. Check it with one smoke run per harness, following `docs/smoke/`:
- a run started outside any repo, where discovery should find two repos in a base folder;
- `/kinetic:init` run with no arguments, from inside a repo and from a folder of repos.

Record the results in `docs/smoke/` as the earlier releases did.
