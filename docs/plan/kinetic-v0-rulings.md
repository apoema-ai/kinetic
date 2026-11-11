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
