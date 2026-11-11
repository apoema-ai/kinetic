---
name: run
description: Drive a kinetic run end to end. Picks the lane, enforces the approval gates, runs the build loop and sequences the phase skills (grill, spec, tickets, tdd, ship, retro). The only orchestrator.
model: sonnet
disable-model-invocation: true
argument-hint: "<JIRA-KEY|idea|spec-path> [--from build]"
---

# Kinetic run

You are the orchestrator. Only you set phases, record gates and dispatch agents. Phase skills are loaded by reading their file and following it, never via the Skill tool: "read and follow `skills/<name>/SKILL.md`" (under `${CLAUDE_PLUGIN_ROOT}`), passing `Run: <run_dir>`.

Run scripts as `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.<module> ...`. Never edit `state.json` by hand and never read code or full diffs yourself: scripts emit JSON, agents write reports, you read report headers.

Guides (read each at the point named, under `${CLAUDE_PLUGIN_ROOT}/skills/run/guides/`):

- `lanes.md`: pick the lane and the entry phase.
- `gates.md`: the three approval gates.
- `build-loop.md`: the build loop and the review phase.
- `recovery.md`: resuming a run.

## 1. Preflight

1. Read `~/.config/kinetic/repos.json` and run `python3 -m kinetic.doctor --repo NAME=PATH` once per entry with a `path` (all in one call). Show warns with their fix (missing reused skills have fallbacks, see `build-loop.md`). Stop on any fail. If there is no repos.json, tell the user to run `/kinetic:init` and stop.
2. Read `~/.config/kinetic/settings.json` for `workspace_root` (default `~/workspace/kinetic-runs`) and `tracker`.
3. If `~/.config/kinetic/active-run` exists and points at a run directory containing `state.json`, read `guides/recovery.md` and follow it instead of initialising. Never pass `--force` to `state init` unless the user explicitly asks to restart.
4. Otherwise the run dir is `<workspace_root>/<run-id>/`, run-id = the Jira key, or a kebab slug of the idea plus the date (`<slug>-YYYY-MM-DD`). For a spec path, slug its file name.

## 2. Start

Read `guides/lanes.md`, pick the lane and entry phase, then:

```
python3 -m kinetic.state init --run <run_dir> --lane <lane> --ref "<ref>"
```

Write the pointer: `printf '%s' <run_dir> | tee ~/.config/kinetic/active-run` (the directory `~/.config/kinetic/` already exists after init).

## 3. Phases

Set each with `python3 -m kinetic.state set-phase --run <run_dir> --phase <phase>` just before starting it. Order: intake, grill, spec, tickets, build, review, ship, retro, done. Skip the phases the lane skips (`lanes.md`).

| Phase | Do |
|---|---|
| grill | Read and follow `skills/grill/SKILL.md`. |
| spec | Read and follow `skills/spec/SKILL.md`, then run the spec gate (`gates.md`). |
| tickets | Epic only: use `find-ticket-repos` if available to confirm repos, else ask the user. Read and follow `skills/tickets/SKILL.md`, then run the breakdown gate (`gates.md`). |
| build | `guides/build-loop.md`, build loop. |
| review | `guides/build-loop.md`, review phase. |
| ship | Read and follow `skills/ship/SKILL.md`, run the ship gate (`gates.md`) first. Offer `dev-fleet:release` only if the user asks and the repo is k8s-hosted. |
| retro | Read and follow `skills/retro/SKILL.md`. Then `set-phase done` and `rm -f ~/.config/kinetic/active-run`. |

A rejected gate returns to the previous phase skill, never forward. Push, PR, Jira writes and deploy are additionally confirmed by hooks: never try to work around a hook decision.

## Rules

- At most 3 implementers at once, at most 1 running per repo; `kinetic.frontier` enforces both.
- Never dispatch an agent from inside an agent; you are the only dispatcher.
- A reused skill that is missing: use the fallback named in the guide, or ask the user. Never fail silently.
- Record every user decision that changes scope with `python3 -m kinetic.state add-ruling --run <run_dir> --what ... --why ... --cost ...`.
