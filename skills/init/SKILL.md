---
name: init
description: Interactive one-time setup for kinetic. Registers repos, detects verify commands, picks the tracker, writes the user-level config, then runs doctor. Safe to re-run.
model: sonnet
disable-model-invocation: true
argument-hint: "[repo-path ...]"
---

# Kinetic init

Set up kinetic. Ask one question at a time, multiple choice where possible. Write only under `~/.config/kinetic/`; never write anything inside a repo.

Run scripts as `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.<module> ...`.

## Steps

1. **Repos.** Use the paths in the arguments; if none, ask which repo paths to register. The default name of each repo is its directory basename; the user may override it.
2. **Detect.** Run `python3 -m kinetic.detect_repos PATH [PATH ...]`. It prints JSON `{path: {"verify": ..., "marker": ...}}`.
3. **Confirm verify.** Ask only about repos whose `verify` is null (ask for the command) or looks unusual (confirm it). Accept the rest silently.
4. **Tracker.** Ask `jira` or `local`. For `jira`, ask the Jira project key, the slice issue type and the child issue type, one at a time.
5. **Workspace.** Default `workspace_root` is `~/workspace/kinetic-runs`; ask only if the user wants another.
6. **Write.**
   - `~/.config/kinetic/repos.json`: one entry per repo keyed by name, `{"path": "<abs path>", "verify": "<command>"}`. Keep existing entries for repos not mentioned now.
   - `~/.config/kinetic/settings.json`: `{"tracker", "jira_project", "slice_issue_type", "child_issue_type", "workspace_root"}`; for `local`, set the three Jira fields to null.
   - If either file already exists, show the diff it would make and ask before overwriting.
7. **Doctor.** Run `python3 -m kinetic.doctor --repo NAME=PATH` once per registered repo (all in one call), show the checks as a table, and give the one-line fix for each warn or fail.

## Rules

- Never guess a verify command; a null stays a question.
- Re-running must not drop repos or settings the user did not change.
