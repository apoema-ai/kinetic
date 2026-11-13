# Kinetic

Kinetic is an SDLC pipeline (grill, discover, specify, decompose, multi-repo build, review, ship, retro) that runs inside a coding agent and drives work through an issue tracker.

## Harnesses

**Harness**:
The coding agent kinetic runs inside and orchestrates the run from: Claude Code, Codex CLI, OpenCode or Devin CLI (never cloud Devin).
_Avoid_: Host, adapter, agent (for the CLI itself), platform

**Harness profile**:
The single record of what one harness can do and where it keeps things: its hook events, whether it can resume a sub-agent or pick a model per dispatch, its question tool, its tool names and its skill and agent locations.
_Avoid_: Capabilities, harness config

**Enforced**:
A guarantee that a hook, plugin or kinetic script makes hold, whatever the agent decides.
_Avoid_: Hard, guaranteed

**Instructed**:
A guarantee that only the skill or agent text asks for, with nothing to stop a violation. The floor kinetic accepts on a harness that cannot enforce it.
_Avoid_: Advisory, soft, best-effort

**Model tier**:
The strength of model an agent needs, either `standard` or `strong`, which each harness maps to a concrete model and reasoning effort.
_Avoid_: Model name (sonnet, opus) in agent definitions, size, class

## Trackers

**Tracker adapter**:
The per-tracker instructions (GitHub, Jira, Linear, local, Orbit, other) that tell kinetic how to read and write tickets in one issue tracker.
_Avoid_: Adapter (unqualified), integration

**Ticket store**:
Where a run's tickets live, behind one interface that `state.py` reads and writes through: the local ticket store (`state.json`) for most trackers, or the Orbit ticket store (Tasks on an Orbit Board) for the `orbit` tracker.
_Avoid_: Adapter, backend, board

## Repos

**Repo root**:
A folder whose direct child git repos the discover phase may scan, saved as `repo_roots` in `settings.json` once the user approves it.
_Avoid_: Workspace, base dir, code folder

**Discovery**:
The phase that settles which repos a run touches, from sources the user approves, and cuts their integration worktrees.
_Avoid_: Repo detection, repo lookup
