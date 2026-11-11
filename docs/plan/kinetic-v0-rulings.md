# kinetic v0: execution rulings

Decisions made while executing `kinetic-sdlc-pipeline-plan.md` where the plan and spec were silent or in conflict. Kept here because the SDD scratch ledger was deleted at the end of the run.

## Interfaces and state
- R1: `graph.validate(tickets, lane, slices=None)`; state has top-level `slices`.
- R2: state has top-level `repos: {name: {path, integration_branch}}`; pin and isolation read paths from it.
- R3: `state.init` stores `run_dir`; reports live in `<run_dir>/reports`.
- R4: verify key is the ticket id, or `repo:<name>` with no ticket; value `{exit_code, log_path, at}`.
- R5: `python3 -m kinetic.verify --run DIR --repo-name NAME --repo-path PATH [--ticket ID]`; exit code is the verify exit code.
- R6: missing verify command error names both config locations.
- R10, R13, R19: `central`/`home` kwargs on verify, pin and doctor so tests never touch the real `~/.config`.
- R11: `set_phase` with phases intake, grill, spec, tickets, build, review, ship, retro, done.
- R12, R24, R25: `record_edit` stamps the repo (or the ticket worktree's repo); nothing for paths under the run dir.
- R14: every verify record carries `repo` and its start time.
- R17, R18: `set_slices`; ids are Jira keys in Jira mode, `NN-<repo>-<slug>` locally.
- R23: `repos.json` entries may carry `path`; settings in `~/.config/kinetic/settings.json`.

## Scheduling and gates
- R7: ship is done when the ship gate is approved in phase ship.
- R9, R9a: one implementer per checkout; at most two at once with disjoint files.
- R15: `snapshot_published` only on upstream tickets that are done, merged or released.
- R16, R20: frontier returns nothing on a cycle; a repo is occupied while any ticket in it is running, needs a decision or is blocked.
- R21: reviewer agents have no Write tool; the orchestrator saves their reply.
- R22: the Stop gate skips repos with an in-flight ticket.
- R30: integration branch is `kinetic/<run-id>/integration` (ticket branches are `kinetic/<run-id>/<id>`).

## Models
- R29, R32: `tickets` runs inline on the orchestrator's model; frontmatter says `sonnet`.

## Process
- R8: Python 3.9 stdlib only, `from __future__ import annotations`, no `match`.
- R26: the plugin validation gate ran at the end (status frontmatter fixed); the interactive dry run is manual.
- R27, R28: no separate Task 14 review; two 2-line re-review findings fixed directly.

## Left for v0.2 (R31, R33)
- `/kinetic:status` lacks PR health and Jira transitions; the other minor review items M4, M5, M7-M10.
- init asks for `pin` on the publishing repo but `gitops.pin` reads the downstream repo (fails safe to merge edges).
- quick-lane test seams have no defined place in the ticket file.
- Jira-mode review fix tickets get a synthetic `Jira key`.
- pin commands are not required to commit.
- recovery cannot tell a dead fix agent from a finished first round.
- validator: no skill evals, no `Use when:` triggers, agents lack `maxTurns`.
- unverified until a live session: `${CLAUDE_PLUGIN_ROOT}` expansion, `skills: [tdd]` resolution, subagent `session_id` in hook payloads.

## 0.3.0: trackers, human tickets, relationship types, PR template

Entries are what / why / cost. R34-R41 are the designer's calls from `docs/specs/kinetic-trackers-human-tickets-pr-template-design.md`; R42 onward are controller rulings made while executing the plan.

### Designer's calls
- R34: ship opens PRs even when a human ticket is still open and marks it as a merge blocker. Why: the code is reviewable before the manual step finishes. Cost: a PR can exist that must not merge yet.
- R35: local ticket files stay in the run folder, not in the repo (`.scratch/`). Why: no stray files in a user's repo and isolation stays simple. Cost: ticket files are not versioned with the code.
- R36: kinetic state stays authoritative; remote trackers are never read back. Why: no Python talks to a tracker and the graph cannot be corrupted by a manual tracker edit. Cost: edits made in the tracker UI do not reach kinetic (the local board reports drift for files only).
- R37: an edge onto a human blocker is satisfied when the blocker is `done`, whatever its edge type. Why: a human ticket has no snapshot or merge to wait for. Cost: a `snapshot` or `release` edge on a human ticket carries no extra meaning.
- R38: `NEEDS_HUMAN` creates a new human ticket and blocks the original on it, instead of converting the original to human. Why: the original keeps its repo, worktree and history. Cost: one extra ticket per human step.
- R39: the `release` edge is kept as it is rather than replaced by human tickets. Why: it already means "wait for a manual mark" and existing runs rely on it. Cost: two ways to express a manual wait.
- R40: the tracker is user-level only; a repo cannot switch it. Why: one run uses one tracker across repos. Cost: no per-repo tracker.
- R41: "blocks only" was selected together with the three new relationships; read as "keep blocks", not "add nothing". Why: the answers conflict literally and dropping `blocks` would break every run. Cost: if "add nothing" was meant, `after`, `ships_with` and `related` are extra.

### Controller rulings
- R42: work directly on main, no worktree; the user approved committing straight to main in kinetic (no remote). Cost if wrong: commits need moving to a branch.
- R43: use the durable test runner in the SDD folder instead of the `/private/tmp` runner the plan names; the tmp one has no `-k` and may vanish. Cost: none.
- R44: Task 9 e2e shape: L2 (lib) is blocked by S1 (merge), as in the existing e2e, and shares `ships_with` "g" with S1; the plan's asserts (`ready == []` after L1, `ready == ["S1"]` after human-done) only hold if L2 waits on S1. Cost if wrong: test shape differs from the plan text only.
- R45: `only_human_left` also requires `waiting_on_you(st)` to be non-empty. Why: the spec says the run pauses for human work the user can act on; the plan's literal condition 4 was true with nothing actionable when a human ticket's own upstream stalled. Cost if wrong: a pure-human-chain run falls into the stalled case and shows edges instead of the pause message.
- R46: local ticket header follows the Task 5 plan (bold `**Key:**` lines; keys Status, Type, Repo, Slice, Blocked by, After, Ships with, Related, Assignee; full ids), not spec section 6's plain lines with Labels. Why: it matches the existing tickets template and local mode has no label concept beyond Type. Cost if wrong: local files differ cosmetically from the spec text.
- R47: local Assignee is derived, not stored (human -> `you`, agent -> `agent`) and drift ignores it. Why: avoids a new state field the spec never defined. Cost if wrong: no per-person assignee in local mode.
- R48: `tracker.resolve` returns `description` only for tracker `other` (None otherwise). Why: spec section 5 scopes tracker_description to `other`. Cost: none.
- R49: Task 7 adds the CLI `gitops ships-with --run <dir>` instead of a `python3 -c` call in skill prose. Why: inline interpreter code triggers permission prompts and every other skill call is an exact command. Cost: one small subcommand in a Task 6 file.
- R50: only `blocked_by` human tickets become WARNING merge blockers; `related`-only human tickets are listed under Manual steps. Why: spec section 7 says "depends on". Cost: none.
- R51: ship step 2 keeps `<dir>/pr/<repo>.placeholders.md` so the step 4 backfill has a source after step 3.1 overwrites the body. Why: the reviewer's out-of-scope note is load-bearing for the Ships with backfill. Cost: one extra file per repo in the run dir.
- R52: `NEEDS_HUMAN` remote tickets store the tracker key in an ad-hoc `tracker_ref` state field (prose reads it if present, else the id), not added to `ticket_defaults`. Why: no code change; `field()` is for Python readers only. Cost if wrong: a later Python reader of `tracker_ref` needs `field()` support.
- R53: hook-confirmation claims are worded as Atlassian MCP and Bash only; Linear and other MCP writes are covered only by the grant. Why: `hooks.json` matches only those. Cost: none (hooks unchanged).
- R54: Task 9 step 3 (the plugin validator skill) is run by the controller after the implementer. Why: the validator is a skill that may dispatch agents and implementers never dispatch subagents. Cost: none.
- R55: this section also records the controller rulings from the SDD ledger, not only the spec's eight designer's calls, because they are decisions made on the user's behalf. Cost: a longer rulings file.

### Left for later (0.3.0)
- The tracker adapters (`trackers/*.md`) are untested live against Jira, GitHub and Linear, including whether the installed `gh` supports sub-issues and "blocked by", and which relation tools the Linear MCP exposes.
- Write hooks confirm only Atlassian MCP and Bash calls; Linear and other MCP writes are not hook-confirmed.
