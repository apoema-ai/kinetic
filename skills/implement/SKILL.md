---
name: implement
description: Start the build lane for a ticket that is already well specified. Checks the ref has acceptance criteria and a repo; otherwise points to /kinetic:run.
model: sonnet
disable-model-invocation: true
argument-hint: "<ticket-ref|ticket-file|spec-path>"
---

# Kinetic implement

Alias for `/kinetic:run <ref> --from build`, with a pre-check. Do not reimplement the orchestrator.

## Validate the ref

Load it: a tracker reference through the adapter's "fetch" operation (resolve the tracker with `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.tracker resolve` and read the adapter file it names), otherwise read the ticket or spec file. It needs both:

- **Acceptance criteria**: a `- [ ]` checklist or an "Acceptance criteria" section.
- **A repo**: a `Repo:` line, a repo field, or exactly one repo registered in `~/.config/kinetic/repos.json`.

If either is missing, say which one and stop: "Not ready to build. Run `/kinetic:run <ref>` so it can grill, spec or detect the repo first."

## Hand off

Otherwise say "Starting the build lane for <ref>", then follow the instructions of the `/kinetic:run` command with `<ref> --from build`. This hand-off is the one sanctioned command-to-command call; do not use the Skill tool for it.
