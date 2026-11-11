---
name: doctor
description: Read-only health check for kinetic. Prints a table of checks (tools, auth, reused skills, repo verify commands) with a one-line fix for each warning or failure.
model: haiku
disable-model-invocation: true
---

# Kinetic doctor

Read-only. Changes nothing.

1. Read `~/.config/kinetic/repos.json`. Collect every entry that has a `path` key. If there are none (or the file is missing), say "No registered repos. Run `/kinetic:init`." and stop.
2. Run `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.doctor --repo NAME=PATH ...` with one `--repo` per collected entry. It prints `{"checks": [{"name", "status", "fix"?}], "ok": bool}` and exits non-zero when any check fails; the JSON is still on stdout.
3. Print the checks as a table (name, status, detail). Under it, list the one-line fix for each `warn` or `fail`.
4. End with one line: all clear, or the count of warnings and failures.
