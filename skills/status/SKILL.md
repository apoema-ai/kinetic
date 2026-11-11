---
name: status
description: "Render the state of a kinetic run: phase, tickets, frontier, gates. Uses the active run unless a run directory is given."
model: haiku
disable-model-invocation: true
argument-hint: "[run-dir]"
---

# Kinetic status

1. Pick the run directory: the argument if given, else the contents of `~/.config/kinetic/active-run`.
2. If neither exists, say there is no active run and suggest `/kinetic:run <ref>`. Stop.
3. Run `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.status --run <dir>` and print its output unchanged.
4. If it fails, show the error and stop. Do not reconstruct state by hand.
