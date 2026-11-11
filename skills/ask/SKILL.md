---
name: ask
description: Router for kinetic. Prints the three lanes, the entry points, and the next command for the current run as computed by the next_step script.
model: haiku
disable-model-invocation: true
---

# Kinetic ask

Print the following, then the next step.

## Lanes

| Lane | When | Phases |
|---|---|---|
| quick | One small ticket, one repo, no design decisions | implement, verify, review, ship |
| feature | One repo, needs a spec | grill, spec, tickets, build, review, ship, retro |
| epic | Several repos | all phases, with repo detection, typed edges, per-repo integration branches |

## What you have and where `/kinetic:run` starts

| What the user has | `run` starts at |
|---|---|
| Idea or bare ticket | grill |
| Spec, no tickets | tickets (repo detection first) |
| Spec and tickets with edges | build (frontier) |
| One small ticket, no spec | quick lane |

Other commands: `/kinetic:implement <ref>` (alias for `run --from build`), `/kinetic:init`, `/kinetic:doctor`, `/kinetic:status`.

## Next step

Run `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.next_step`. It uses the active run (`~/.config/kinetic/active-run`) and prints JSON `{"command", "reason"}`. Render it as exactly:

`Next: <command> — <reason>`

Do not add, reorder or invent any other next step. If the script fails, show its error.
