---
name: init
description: Interactive one-time setup for kinetic. Registers repos, detects verify commands, picks the tracker and its names, writes the user-level config, then runs doctor. Safe to re-run.
model: sonnet
disable-model-invocation: true
argument-hint: "[repo-path ...]"
---

# Kinetic init

Set up kinetic. Ask one question at a time, multiple choice where possible. Write only under `~/.config/kinetic/`; never write anything inside a repo.

Run scripts as `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.<module> ...`.

Run this outside the session that owns the active run: in that session the isolation hook denies the config writes below. Any other session works, or finish or abandon the run first.

## Steps

1. **Repos.** Use the paths in the arguments; if none, ask which repo paths to register. The default name of each repo is its directory basename; the user may override it.
2. **Detect.** Run `python3 -m kinetic.detect_repos PATH [PATH ...]`. It prints JSON `{path: {"verify": ..., "marker": ...}}`.
3. **Confirm verify.** Ask only about repos whose `verify` is null (ask for the command) or looks unusual (confirm it). Accept the rest silently.
3b. **Snapshots.** For each repo ask, one at a time and only if it publishes snapshot builds other repos consume: the `publish_snapshot` command (builds and publishes a snapshot) and the `pin` command (run in the downstream repo; it reads `KINETIC_UPSTREAM_REF`). Leave both unset otherwise: the tickets phase then uses `merge` edges between repos instead of `snapshot` edges.
4. **Tracker.** Four questions, one at a time:
   1. Which tracker: `jira`, `github`, `linear`, `local` or `other`. Recommend `jira` if the Atlassian MCP is connected, `github` if the repos are on GitHub.
   2. That tracker's required settings (read its adapter, `trackers/<name>.md`). For `other`, also ask for a short description of the tracker and how to reach it; it is written as top-level `tracker_description`, which resolve requires.
   3. "Keep the default names?" (recommend yes). On no, collect overrides for the kind, edge and status names.
   4. "Use the default PR template?" (recommend yes). On no, ask the template's path.
5. **Workspace.** Default `workspace_root` is `~/workspace/kinetic-runs`; ask only if the user wants another.
6. **Write.**
   - `~/.config/kinetic/repos.json`: one entry per repo keyed by name, `{"path": "<abs path>", "verify": "<command>"}`, plus `"publish_snapshot"` and `"pin"` when given. Keep existing entries for repos not mentioned now.
   - `~/.config/kinetic/settings.json`: `{"tracker", "tracker_settings", "workspace_root"}`, plus `tracker_description` for `other`, `tracker_names` only when overridden and `pr_template` only when a path was given. Old top-level keys already there (the 0.2.0 tracker keys) are kept; they are still read.
   - If either file already exists, show the diff it would make and ask before overwriting.
6b. **Labels.** Resolve the tracker with `python3 -m kinetic.tracker resolve`, and with the adapter's "fetch" operation check that each label in `names` (kind, edge, ships-with) exists. List the missing ones and ask before creating any: creating a label is a tracker write. Create only on a yes; on a no, leave them (doctor warns).
7. **Doctor.** Run `python3 -m kinetic.doctor --repo NAME=PATH` once per registered repo (all in one call), show the checks as a table, and give the one-line fix for each warn or fail.

## Rules

- Never guess a verify command; a null stays a question.
- Re-running must not drop repos or settings the user did not change.
