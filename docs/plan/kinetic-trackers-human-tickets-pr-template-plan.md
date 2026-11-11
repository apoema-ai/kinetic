# Trackers, human-ready tickets, relationship types and PR template: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kinetic tickets can be agent or human work, carry soft precedence, ships-with and related links, mirror to Jira, GitHub, Linear, local markdown or a prose-described tracker, and ship PR bodies from a default or user template.

**Architecture:** Kinetic state (`state.json`) stays authoritative. The scripts get new ticket fields and rules: `state`, `graph`, `frontier`, `gitops.merge_order` and `status`. There are two new scripts: `tracker.py` resolves the settings and the adapter names, and `board.py` renders and diffs the local markdown. Tracker I/O stays in skill prose. Each tracker is one markdown adapter under `trackers/`. The PR layout moves to `templates/pr-body.md`.

**Tech Stack:** Python 3.9 stdlib only, `unittest`, markdown skills and agents.

**Spec:** [docs/specs/kinetic-trackers-human-tickets-pr-template-design.md](../specs/kinetic-trackers-human-tickets-pr-template-design.md)

## Global Constraints

- Python 3.9 stdlib only. Every module starts with `from __future__ import annotations`. No `match`.
- No skill calls another skill. No subagent dispatches a subagent. Only `/kinetic:run` orchestrates.
- No Python talks to a tracker. Adding a tracker adds only a `trackers/<name>.md` file.
- Local mode stays markdown a person can read. No binary or database store.
- 0.2.0 state files and settings keep working with no migration:
  - missing fields default to `kind=agent`, `after=[]`, `ships_with=null`, `related=[]`, `human_note=null`;
  - `tracker: jira|local` and the top-level `jira_project` / `slice_issue_type` / `child_issue_type` keys are still read.
- Version: bump `.claude-plugin/plugin.json` to `0.3.0` in Task 1. Every later commit ships under 0.3.0.
- Git:
  - Stage only by explicit path. Never stage, restore or commit the old Byond changes or `.claude-plugins/`.
  - Commit straight to `main`. There is no remote.
  - No co-author trailer.
  - Run every git call as `git -C ~/workspace/lab/kinetic ...`.
- Tests:
  - Run them with `python3 /private/tmp/claude-504/-Users-rmendes--claude-spares-spare-9gYGC4/ad9c5724-2a7b-4840-b493-cd62df84668c/scratchpad/run_kinetic_tests.py`.
  - If that runner is gone, write an equivalent one. It must chdir to the repo, set `os.environ["PYTHONPATH"]="scripts"`, add `scripts` and the repo root to `sys.path`, and run unittest discover on `tests` under `if __name__ == "__main__":`.
  - The single-test form below (`python3 -m unittest tests.<module>.<Class>.<test>`) also needs `PYTHONPATH=scripts`, and env prefixes are blocked. Use the runner with a `-k <pattern>` argument if it supports one; otherwise add `sys.argv` pass-through to it.
- Every frontmatter must parse with `yaml.safe_load`. Quote any `description` that contains `: `.

## Review Focus

1. **A 0.2.0 `state.json` with none of the new fields:** `frontier`, `graph`, `status` and `merge_order` must behave exactly as before. Test: `test_legacy_ticket_without_new_fields` in Task 3, using tickets that lack `kind`, `after`, `ships_with` and `related`.
2. **Marking a human ticket done through `set-ticket --field status=done`:** must be refused with a pointer to `human-done`. Setting `kind=human` and `status=done` in the same `set-ticket` call must also be refused. Tests in Task 1.
3. **A hand-edited local ticket file with unknown or malformed header lines,** such as a misspelled key or a status that doesn't exist: `board.drift` reports it as a difference and never raises. Test in Task 5.
4. **A user PR template whose file is missing,** set in either config: a hard error naming the path, never a silent fallback to the default. Test in Task 4 (`tracker.pr_template`).
5. **A run where every remaining ticket is human, or blocked only behind human tickets:** `only_human_left` is true, so the run doesn't count as stalled. A run with a todo agent ticket stuck behind an unpublished snapshot is not `only_human_left`. Tests in Task 3.

---

### Task 1: Ticket model and human-done (`state.py`)

**Files:**
- Modify: `scripts/kinetic/state.py`
- Modify: `.claude-plugin/plugin.json` (version `0.3.0`)
- Test: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `KINDS = ("agent", "human")`
  - `ticket_defaults() -> dict` returns the full default ticket. That is the current keys plus `kind="agent"`, `after=[]`, `ships_with=None`, `related=[]`, `human_note=None` and `done_by=None`.
  - `field(t: dict, name: str)` returns `t.get(name, ticket_defaults()[name])`. Later tasks read the new fields only through it.
  - `human_done(run_dir, ticket_id: str, note: str | None = None) -> dict`
  - CLI `human-done --run --id [--note]`
- `set_ticket` validates the new fields:
  - `kind` must be in `KINDS`;
  - `after` and `related` must be lists of str;
  - `ships_with` must be a str or None.

  The CLI's `_parse_field` already JSON-decodes `[` values. `ships_with=null` must decode to None.

- [ ] **Step 1: Write the failing tests** in `tests/test_state.py`, class `HumanTicketTest`:
  - `test_defaults_include_new_fields`: after `set_ticket(run, "A", repo="r")`, the ticket has `kind == "agent"`, `after == []`, `ships_with is None`, `related == []`, `human_note is None` and `done_by is None`.
  - `test_invalid_kind_rejected`: `set_ticket(run, "A", kind="robot")` raises `ValueError` mentioning `kind`.
  - `test_human_done_sets_fields_without_verify`: given `set_ticket(run, "H", kind="human")`, then `human_done(run, "H", "tf apply ok")`, the result has `status == "done"`, `done_by == "human"` and `human_note == "tf apply ok"`, with no verify record.
  - `test_human_done_rejects_agent_ticket`: `human_done` on an agent ticket raises `ValueError` mentioning `kind=human`.
  - `test_set_ticket_done_refused_for_human`: `set_ticket(run, "H", require_verify=True, status="done")` on a human ticket raises `ValueError` containing `human-done`.
  - `test_set_ticket_kind_human_and_done_together_refused`: `set_ticket(run, "N", require_verify=True, kind="human", status="done")` raises.
  - `test_cli_human_done`: `main(["human-done", "--run", run, "--id", "H", "--note", "x"])` returns 0.
  - `test_cli_ships_with_null`: `main(["set-ticket", ..., "--field", "ships_with=null"])` stores None.
- [ ] **Step 2: Run them and confirm they fail.** Use the runner (see Global Constraints). Expected: the failures name `human_done`, `KINDS` or `ticket_defaults`.
- [ ] **Step 3: Implement.**
  - `set_ticket` uses `ticket_defaults()` for `setdefault`.
  - In `fn`, when `fields.get("status") in DONE_STATUSES` and the ticket's resulting kind is `human`, raise `ValueError("ticket <id> is a human ticket: mark it done with `kinetic.state human-done`")`. Do this whatever `require_verify` is.
  - `human_done` raises if the ticket is missing or not human. Otherwise it writes `status`, `done_by` and `human_note` directly through `_mutate`, bypassing that check.
  - `_parse_field` maps the literal `null` to None for `ships_with` and `human_note`.
- [ ] **Step 4: Run the full suite.** Expected: all pass, with 180 plus the new tests.
- [ ] **Step 5: Bump** `.claude-plugin/plugin.json` `version` to `0.3.0`.
- [ ] **Step 6: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/state.py tests/test_state.py .claude-plugin/plugin.json
git -C ~/workspace/lab/kinetic commit -m "feat(state): ticket kind, soft links and human-done (0.3.0)"
```

### Task 2: Graph validation and soft-precedence topo (`graph.py`)

**Files:**
- Modify: `scripts/kinetic/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `state.field(t, name)` (Task 1).
- `topo_order(tickets)` keeps its signature. Its new tie-break: among tickets whose `blocked_by` are all placed, pick the one whose `after` targets (known ids only) are all placed. Ties go to the smallest id. If no candidate qualifies, the soft links are in a cycle among themselves: pick the smallest id. Soft links never raise.
- `validate(tickets, lane, slices=None) -> list` adds these errors, as exact substrings:
  - a human ticket with no repo is fine; `missing repo` stays for agent tickets only;
  - `ticket {i}: unknown after '{x}'`;
  - `ticket {i}: unknown related '{x}'`;
  - `ticket {i}: after '{x}' contradicts blocks` when `i` is in `_upstream(tickets, x)`, that is, `x` is blocked by `i`;
  - `ships_with group '{g}' has one ticket ({i})`.
- Produces: `soft_warnings(tickets) -> list[str]`, with `soft precedence cycle among: a, b` when the `after` links form a cycle. `main validate` prints `warnings = interface_issues(...)["warnings"] + soft_warnings(...)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_graph.py`, class `SoftLinksTest`. Use the existing helpers, or tickets built as `{"repo": "r", "blocked_by": [], **extra}`.
  - `test_after_breaks_ties`: given `A` and `B` with no blocks, and `A.after=["B"]`, `topo_order` returns `["B", "A"]`.
  - `test_after_never_overrides_blocks`: given `B` blocked by `A` (merge) and `A.after=["C"]` with `C` free, the order puts `A` before `B` and `C` before `A`.
  - `test_after_cycle_does_not_raise`: given `A.after=["B"]` and `B.after=["A"]`, `topo_order` returns `["A", "B"]`, and `soft_warnings` has one item containing `soft precedence cycle`.
  - `test_human_ticket_needs_no_repo`: given `H` with `kind="human"` and `repo=None`, `validate` returns `[]`.
  - `test_unknown_after_and_related`: the two error substrings appear.
  - `test_after_contradicts_blocks`: given `B` blocked by `A` and `A.after=["B"]`, the error substring appears.
  - `test_single_ticket_ships_with_group`: the error substring appears.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** per the Interfaces block. Replace the heap with a sorted pick each round; O(n²) is fine for run sizes.
- [ ] **Step 4: Run the full suite.** Expected: all pass, including the existing `topo` tests.
- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/graph.py tests/test_graph.py
git -C ~/workspace/lab/kinetic commit -m "feat(graph): soft precedence ordering and validation of new links"
```

### Task 3: Frontier report (`frontier.py`) and status block (`status.py`)

**Files:**
- Modify: `scripts/kinetic/frontier.py`, `scripts/kinetic/status.py`
- Test: `tests/test_frontier.py`, `tests/test_status.py`

**Interfaces:**
- Consumes: `state.field` and `graph.topo_order` (Tasks 1 and 2).
- `ready(st, cap=3) -> list[str]` keeps its signature. Human tickets are never in it.
- `_satisfied(edge, blocker)`: if `field(blocker, "kind") == "human"`, return `blocker["status"] in DONE`. The type rules apply only otherwise.
- Produces:
  - `waiting_on_you(st) -> list[str]`: the human tickets that are `todo` with every blocker satisfied, in topo order.
  - `only_human_left(st) -> bool`: true when all of these hold:
    1. `ready(st)` is empty;
    2. no ticket is in `OCCUPYING`;
    3. at least one ticket is `todo`;
    4. every `todo` ticket is human, or has a transitive blocker that is a `todo` human ticket.
  - `report(st, cap=3) -> dict`: `{"ready": [...], "waiting_on_you": [...], "only_human_left": bool}`. The CLI prints `report`.
- `status.render` adds a `Waiting on you: <ids or none>` line above `Ready:`, plus a `kind` column in the ticket table.

- [ ] **Step 1: Write the failing tests** in `tests/test_frontier.py`, class `HumanFrontierTest`. Extend the helper `t(...)` with `kind="agent"`.
  - `test_human_ticket_not_dispatched`: given `{"H": t(None, kind="human")}`, `ready` is `[]` and `waiting_on_you` is `["H"]`.
  - `test_edge_onto_human_satisfied_when_done`: given `H` (human, status `done`) and `B` blocked by `H` (merge), `ready` is `["B"]`.
  - `test_edge_onto_human_waits_while_todo`: same with `H` `todo`. `ready` is `[]` and `only_human_left` is true.
  - `test_snapshot_stall_is_not_only_human_left`: given `A` done and unpublished and `B` blocked by `A` (snapshot), `only_human_left` is false.
  - `test_independent_agent_work_continues`: given `H` (human, todo), `B` blocked by `H`, and `C` free, `ready` is `["C"]`.
  - `test_soft_precedence_orders_ready`: given `A` (r1) and `B` (r2) free, with `A.after=["B"]`, `ready` is `["B", "A"]`.
  - `test_legacy_ticket_without_new_fields`: tickets built without `kind` give the same `ready` as the existing tests.
  - `test_cli_prints_report`: the CLI output JSON has the three keys.
  - In `tests/test_status.py`: `test_render_shows_waiting_on_you` checks the line `Waiting on you: H`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** per the Interfaces block.
  - In `ready`, skip `kind == "human"` tickets.
  - Human tickets have no repo, so they never enter `busy`.
- [ ] **Step 4: Run the full suite.** Expected: all pass. `test_e2e_scripts` still uses `frontier.ready`, unchanged.
- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/frontier.py scripts/kinetic/status.py tests/test_frontier.py tests/test_status.py
git -C ~/workspace/lab/kinetic commit -m "feat(frontier): human tickets wait on you, only-human-left, soft order"
```

### Task 4: Tracker settings and adapters (`tracker.py`, `trackers/*.md`)

**Files:**
- Create: `scripts/kinetic/tracker.py`
- Create: `trackers/jira.md`, `trackers/github.md`, `trackers/linear.md`, `trackers/local.md`, `trackers/other.md`
- Test: `tests/test_tracker.py`

**Interfaces:**
- Produces:
  - `TRACKERS = ("jira", "github", "linear", "local", "other")`
  - `ROLES`: the keys every adapter's defaults must hold. These are `kind.agent`, `kind.human`, `edge.snapshot`, `edge.merge`, `edge.release`, `after`, `ships_with`, `related`, and `status.{todo,running,done,merged,blocked}`.
  - `REQUIRED = {"jira": ["jira_project", "slice_issue_type", "child_issue_type"], "github": ["github_repo"], "linear": ["linear_team"], "local": [], "other": []}`
  - `class TrackerError(Exception)`
  - `adapter_defaults(path: Path) -> dict`: parses the first fenced `json` block in the adapter file. It raises `TrackerError` if the block is missing or lacks a role.
  - `resolve(settings: Path = DEFAULT_SETTINGS, plugin_root: Path = ROOT) -> dict`: returns `{"tracker", "adapter": str(path), "settings": {...}, "names": {...}, "description": str | None}`.
    - With no settings file, or no `tracker` key, it returns `local`.
    - Legacy top-level Jira keys are folded into `settings`.
    - `tracker_names` is deep-merged over the defaults.
    - It raises `TrackerError` for an unknown tracker, a missing `REQUIRED` key, or `other` without `tracker_description`.
  - `pr_template(repo_path: Path | None, settings: Path = DEFAULT_SETTINGS, plugin_root: Path = ROOT) -> str`: picks the first of `.kinetic.json` `pr_template`, the settings `pr_template`, and `<plugin_root>/templates/pr-body.md`. If a configured file is missing, it raises `TrackerError` naming the path.
  - CLI `python3 -m kinetic.tracker resolve` and `python3 -m kinetic.tracker pr-template [--repo PATH]` print JSON. On a `TrackerError` they print to stderr and exit 1.
  - `DEFAULT_SETTINGS = Path.home() / ".config/kinetic/settings.json"`. `ROOT` is the plugin root (`Path(__file__).resolve().parents[2]`).
- Adapter files follow the spec's "Tracker adapters" section. Each one has:
  - an `## Operations` section with one `###` per operation: create slice parent, create child, link blocker, link after, link ships-with, link related, set kind, move status, assign to user, fetch, comment, ticket reference;
  - a `## Default names` section with the json block;
  - for GitHub and Linear, a `## Fallbacks` note: where the native relationship is missing in the installed `gh` or Linear MCP, use the label or body line, and say so in the run log.

  The local adapter points to `board.py` (Task 5) for every write. The other adapter says to follow `tracker_description` and to ask the user when an operation isn't covered.

- [ ] **Step 1: Write the failing tests** in `tests/test_tracker.py`. Use temp settings files.
  - `test_no_settings_is_local`
  - `test_legacy_jira_keys`: `{"tracker": "jira", "jira_project": "INV", "slice_issue_type": "Epic", "child_issue_type": "Story"}` resolves with those values in `settings`.
  - `test_names_deep_merge`: `tracker_names: {"kind": {"human": "needs-ops"}}` gives `names["kind"] == {"agent": "kind:agent", "human": "needs-ops"}`.
  - `test_unknown_tracker_raises`
  - `test_github_requires_repo`
  - `test_other_requires_description`
  - `test_every_adapter_has_all_roles`: loops over `TRACKERS` and calls `adapter_defaults` on the real files.
  - `test_pr_template_default`: the result ends with `templates/pr-body.md`. This needs Task 7's file, so create a placeholder `templates/pr-body.md` here with only `<<TICKETS>>`; Task 7 fills it.
  - `test_pr_template_repo_wins`
  - `test_pr_template_missing_file_raises`
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** `tracker.py`, and write the five adapters with the defaults from the spec's table and json sample.
- [ ] **Step 4: Run the full suite.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/tracker.py tests/test_tracker.py trackers/jira.md trackers/github.md trackers/linear.md trackers/local.md trackers/other.md templates/pr-body.md
git -C ~/workspace/lab/kinetic commit -m "feat(tracker): pluggable tracker adapters and settings resolution"
```

### Task 5: Local markdown board and drift (`board.py`)

**Files:**
- Create: `scripts/kinetic/board.py`
- Test: `tests/test_board.py`

**Interfaces:**
- Consumes: `state.load`, `state.field`, `graph.topo_order` and `frontier.waiting_on_you`.
- **Header grammar.** These lines are the existing template's bold-key lines. A ticket file starts with `# <title>`, then lines `**<Key>:** <value>` up to the first line that is not a header line. Kinetic owns these keys, in this order:
  - `Status`
  - `Type`
  - `Repo`
  - `Slice`
  - `Blocked by`
  - `After`
  - `Ships with`
  - `Related`
  - `Assignee`

  Value formats:
  - `Blocked by: 01-lib-x (merge), 02-svc-y (snapshot)`, or `None`;
  - `After` and `Related` as comma-separated ids or `None`;
  - `Ships with` as a group name or `None`;
  - `Type` as `agent` or `human`.

  Other bold-key lines, such as `What to build` and `Interfaces`, are kept as they are.
- Produces:
  - `HEADER_KEYS` (the tuple above)
  - `header_lines(t: dict) -> list[str]`
  - `parse_header(text: str) -> dict[str, str]`
  - `write_header(run_dir, ticket_id) -> Path`: rewrites that file's owned lines in place, inserting any that are missing after the title, and leaves the rest of the file untouched.
  - `render(run_dir) -> Path`: writes `<run_dir>/issues/README.md`. It is a table `| id | title | type | status | blocked by | after |`, with the `waiting_on_you` tickets first under a `## Waiting on you` heading, then the rest in topo order. Titles come from each file's `# ` line.
  - `drift(run_dir) -> list[dict]`: returns `{"id", "key", "file", "state"}` for every owned key whose file value differs from state. A file with an unparseable value reports the raw string and never raises. An unknown status string is reported, never applied.
  - CLI `render | header --id | drift`, each with `--run`. They print JSON. `drift` exits 0 whether or not there are differences.
- A ticket's file path is `<run_dir>/issues/<id>.md`. That is the existing local id rule: the id is `NN-<repo>-<slug>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_board.py`:
  - `test_header_roundtrip`: `parse_header("\n".join(header_lines(t)))` gives back the same values.
  - `test_write_header_keeps_body`: a file with `**What to build:** x` and acceptance criteria keeps both after `write_header`.
  - `test_render_waiting_first`: a human todo ticket appears under `## Waiting on you`, above the agent table.
  - `test_drift_reports_hand_edit`: changing `**Status:** todo` to `**Status:** done` in the file gives `[{"id": ..., "key": "Status", "file": "done", "state": "todo"}]`.
  - `test_drift_malformed_value_does_not_raise`: `**Status:** dnoe` and `**Blocked by:** ???` are reported.
  - `test_drift_none_when_in_sync`
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** per the Interfaces block.
- [ ] **Step 4: Run the full suite.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/board.py tests/test_board.py
git -C ~/workspace/lab/kinetic commit -m "feat(board): readable local tracker board, header sync and drift"
```

### Task 6: Ships-with in merge order (`gitops.merge_order`) and doctor checks

**Files:**
- Modify: `scripts/kinetic/gitops.py:45-70`, `scripts/kinetic/doctor.py`
- Test: `tests/test_gitops.py`, `tests/test_doctor.py`

**Interfaces:**
- Consumes: `state.field` and `tracker.resolve` / `tracker.pr_template`.
- `merge_order(st)` keeps its signature and its constraints. The tie-break changes: among the repos ready at a step, prefer one that shares a `ships_with` group with the repo appended last, then the smallest name. Edges onto human tickets are ignored, as today, because those tickets have no repo.
- Produces: `ships_with_groups(st) -> dict[str, list[str]]`, mapping each group to its sorted repos. Ship uses it for the "Merge together with" line.
- `doctor.checks(...)` gains these entries:
  - `tracker` (`pass`, or `fail` with the `TrackerError` text);
  - `tracker-access`:
    - `github`: reuse the `gh-auth` result;
    - `jira` or `linear`: `warn` with "check the MCP with /mcp";
    - `local` or `other`: `pass`;
  - `pr-template` (`pass`, or `fail` with the missing path).

  Each check takes an injectable `settings` path for tests.

- [ ] **Step 1: Write the failing tests:**
  - `test_merge_order_ships_with_adjacent`: given repos `a`, `b` and `z` with no edges, and `a` and `z` in group `g`, the order is `["a", "z", "b"]`.
  - `test_ships_with_groups`
  - `test_doctor_tracker_fail_on_unknown`
  - `test_doctor_pr_template_missing`
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/gitops.py scripts/kinetic/doctor.py tests/test_gitops.py tests/test_doctor.py
git -C ~/workspace/lab/kinetic commit -m "feat: ships-with merge adjacency and tracker/template doctor checks"
```

### Task 7: PR body template and the ship skill

**Files:**
- Modify: `templates/pr-body.md` (replace the Task 4 placeholder), `skills/ship/SKILL.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `tracker.pr_template`, `tracker.resolve` (for ticket references) and `gitops.ships_with_groups`.
- `templates/pr-body.md`:
  - It is the current layout from `skills/ship/SKILL.md:99-131`, with each section's content replaced by its placeholder, in this order:
    1. `### Tickets:` with `<<TICKETS>>`;
    2. `### Description:` with `<<DESCRIPTION>>`;
    3. `#### Design decisions` with `<<DESIGN_DECISIONS>>`;
    4. `#### Architecture` with `<<ARCHITECTURE>>`;
    5. `### Attention points:` with `<<ATTENTION_POINTS>>`;
    6. `### Manual steps:` with `<<MANUAL_STEPS>>`;
    7. `### Ships with:` with `<<SHIPS_WITH>>`;
    8. `### Related PRs:` with `<<RELATED_PRS>>`;
    9. `### Depends on:` with `<<DEPENDS_ON>>`.
  - Its first line is the title pattern, as an HTML comment: `<!-- title: <<TITLE_KEY>>: <title> -->`.
- `skills/ship/SKILL.md`:
  - Replace the inlined layout with:
    - "Resolve the template with `python3 -m kinetic.tracker pr-template --repo <worktree>`";
    - a placeholder table of what fills each one;
    - "unknown `<<NAME>>` placeholders stay as they are and are listed in the ship report".
  - Keep every writing rule, and add these:
    - **Manual steps:** each human ticket this repo's tickets are blocked by or related to, as `- <ref> - <title> (done by human: <note or link>)`. An open one also goes into the WARNING alert as a merge blocker. Ship still opens the drafts.
    - **Ships with:** "Merge together with: <org>/<repo>#<n>, ..." from `ships_with_groups`.
    - **Tickets and title key:** both come from the adapter's ticket reference operation, not from Jira or local mode branches.
  - The attribution line stays.
- [ ] **Step 1: Write the failing tests** in `tests/test_templates.py`:
  - `test_default_template_has_all_placeholders`: the names are `TICKETS TITLE_KEY DESCRIPTION DESIGN_DECISIONS ARCHITECTURE ATTENTION_POINTS MANUAL_STEPS SHIPS_WITH RELATED_PRS DEPENDS_ON`.
  - `test_ship_skill_does_not_inline_layout`: `skills/ship/SKILL.md` does not contain `### Tickets:\n- <KEY`, and does contain `kinetic.tracker pr-template`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Write** the template and the ship skill changes.
- [ ] **Step 4: Run the full suite** and the frontmatter parse check. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add templates/pr-body.md skills/ship/SKILL.md tests/test_templates.py
git -C ~/workspace/lab/kinetic commit -m "feat(ship): PR body from default or user template, manual steps and ships-with"
```

### Task 8: Tracker-agnostic skills and agents, human tickets in the loop

**Files:**
- Modify:
  - `skills/tickets/SKILL.md`, `skills/run/SKILL.md`, `skills/run/guides/build-loop.md`, `skills/run/guides/gates.md`, `skills/run/guides/lanes.md`
  - `skills/spec/SKILL.md`, `skills/implement/SKILL.md`, `skills/init/SKILL.md`, `skills/doctor/SKILL.md`, `skills/status/SKILL.md`
  - `agents/implementer.md`, `agents/spec-reviewer.md`, `agents/integration-reviewer.md`
- Test: `tests/test_skill_text.py`

**Interfaces:**
- Consumes: the `state human-done` CLI, the `frontier` report, `tracker resolve`, `board render|header|drift` and `pr-template`.
- **Every skill or agent that mentions Jira** now says: "resolve the tracker with `python3 -m kinetic.tracker resolve`, read the adapter file it names, and follow its operation". Adapters are the only place tracker names appear.
  - The brief line `Ticket file: ... (or, in jira mode: Jira key: <id>)` becomes `Ticket ref: <id>` and `Tracker adapter: <path>`, plus `Ticket file:` in local mode.
- **tickets:**
  - Each child gets `Type`, and `After`, `Ships with` and `Related` where they apply. These are passed with `set-ticket --field`.
  - The breakdown table has a `type` column and a one-line reason for each human ticket, and lists human tickets first.
  - Human tickets are a checklist of manual steps with the expected outcome, and have no Interfaces section.
  - The local template gains the owned header lines from Task 5.
- **build-loop and run:**
  - In each round, print `waiting_on_you` with each ticket's checklist, the tickets blocked behind it and its tracker link.
  - When `only_human_left`, stop with "Only human tickets are left: <list>. Tell me when one is done." This is a separate case before the stalled case.
  - On "done with <id>", run `human-done` (with `--note` if given), mirror it through the adapter and re-run the frontier.
  - In local mode, run `board drift` at the start of each round. If anything differs, show the differences and ask: apply each through `set-ticket` / `human-done`, or overwrite the file with `board header`. Run `board header` and `board render` after every state change.
- **NEEDS_HUMAN return:**
  1. create a human ticket `<id>-human-N` from the report's `Manual step:` section;
  2. append it to the original's `blocked_by` with type `merge`;
  3. set the original back to `todo`, keeping its worktree and branch;
  4. show the new ticket to the user.
- **implementer.md:**
  - Add `NEEDS_HUMAN` to the status list: "a step only a person can do (credentials, infra apply, manual config, a decision); write it under `Manual step:` with why and the expected outcome, then stop."
  - Add the `Ticket ref` and `Tracker adapter` brief lines.
- **init:** four questions, one at a time, per the spec's Init section. It writes `settings.json` with `tracker`, `tracker_settings`, optional `tracker_names` and optional `pr_template`. It offers to create missing labels and asks first, since that is a tracker write.
- **doctor and status skills:** show the new checks and the "Waiting on you" block. The doctor skill also checks that the configured labels exist, using the adapter's fetch operation, read-only. Each missing label is a `warn`, and the fix is "run /kinetic:init to create it".
- **Tests:**
  - `test_no_jira_outside_adapters`: no file under `skills/` or `agents/` contains `jira mode`, `Jira key:` or `getJiraIssue`. Only `trackers/jira.md` may.
  - `test_implementer_has_needs_human`
  - `test_build_loop_mentions_only_human_left_and_human_done`
  - `test_all_frontmatter_parses`, which parses every SKILL.md and agent frontmatter with `yaml.safe_load`. If `yaml` isn't importable, the test is skipped; note it in the commit message.
- [ ] **Step 1: Write the failing tests.**
- [ ] **Step 2: Run them and confirm they fail.** Expected: `test_no_jira_outside_adapters` lists the current files.
- [ ] **Step 3: Edit** the skills and agents per the Interfaces block. Keep each edit to the tracker and human-ticket parts; don't rewrite unrelated text.
- [ ] **Step 4: Run the full suite.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add skills/tickets/SKILL.md skills/run/SKILL.md skills/run/guides/build-loop.md skills/run/guides/gates.md skills/run/guides/lanes.md skills/spec/SKILL.md skills/implement/SKILL.md skills/init/SKILL.md skills/doctor/SKILL.md skills/status/SKILL.md agents/implementer.md agents/spec-reviewer.md agents/integration-reviewer.md tests/test_skill_text.py
git -C ~/workspace/lab/kinetic commit -m "feat(skills): tracker adapters everywhere, human tickets and NEEDS_HUMAN in the build loop"
```

### Task 9: End-to-end, README and validation

**Files:**
- Modify: `tests/test_e2e_scripts.py`, `README.md`, `docs/plan/kinetic-v0-rulings.md`

**Interfaces:**
- Consumes: everything above.
- **New e2e test,** `test_epic_flow_with_human_and_ships_with`, built on the existing two-repo fixture:
  - `L1` (lib), then `H1` (human, no repo, blocked by `L1` merge), then `S1` (svc, blocked by `H1` merge), with `S1` and `L2` in `ships_with="g"`.
  - Asserts:
    - `validate == []`;
    - after `L1` merges, `ready == []`, `waiting_on_you == ["H1"]` and `only_human_left` is true;
    - after `human_done(run, "H1", "ok")`, `ready == ["S1"]`;
    - after all merge, `ships_with_groups(st) == {"g": ["lib", "svc"]}`;
    - `board.render` lists every ticket.
- **README:**
  - Sections for trackers (the choice and the names override), human tickets (`human-done`, NEEDS_HUMAN, only-human-left), relationship types, the local board and drift, and the PR template override.
  - Status and known limitations: the adapters are untested live against Jira, GitHub and Linear.
- **Rulings file:** record the eight designer's calls from the spec as rulings, with why and cost.
- [ ] **Step 1: Write the e2e test** and run it. Expected: PASS, since Tasks 1–8 are in.
- [ ] **Step 2: Run the full suite.** Report the exact pass and fail counts.
- [ ] **Step 3: Run `/claude-code-upgrade:validating-claude-code-plugins ~/workspace/lab/kinetic`.** Fix any new failure it attributes to these changes. The deferred v0.2 items (evals, "Use when:", `maxTurns`) stay deferred.
- [ ] **Step 4: Update** the README and the rulings file.
- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add tests/test_e2e_scripts.py README.md docs/plan/kinetic-v0-rulings.md
git -C ~/workspace/lab/kinetic commit -m "test(e2e): human ticket and ships-with flow; docs for 0.3.0"
```

## Not covered by this plan's tests

- The adapters' prose against real Jira, GitHub and Linear. This needs a live dry run per tracker.
- Whether the installed `gh` supports sub-issues and "blocked by", and which relation tools the Linear MCP exposes. The adapters' fallbacks cover the gap, but no test checks it.
