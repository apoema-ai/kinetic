---
name: doctor
description: Read-only health check for kinetic. Prints a table of checks (tools, auth, harness install, reused skills, repo verify commands, tracker, PR template) with a one-line fix for each warning or failure.
model: haiku
disable-model-invocation: true
---

# Kinetic doctor

Read-only. Changes nothing.

1. Read `~/.config/kinetic/repos.json`. Collect every entry that has a `path` key. If there are none (or the file is missing), say "No registered repos. Run `/kinetic:init`." and stop.
2. Run `kinetic doctor --repo NAME=PATH ...` with one `--repo` per collected entry. It prints `{"checks": [{"name", "status", "fix"?}], "ok": bool, "harness", "clone"?, "tiers"?, "guarantees"?}` and exits non-zero when any check fails; the JSON is still on stdout. The checks include the harness install state (`harness`, `install-manifest`, `hooks-registered`, `tier-mapping`, plus `hooks-trusted` where the harness has a trust step) and companion skills looked up in the active harness's skill dirs; plugin companions report `n/a, fallback used` where the harness cannot install them.
2b. Label check, read-only: resolve the tracker with `kinetic tracker resolve`, read the adapter file it names and, with its "fetch" operation, check that each concrete label in `names` (`names.kind.*` and `names.edge.*`) exists; never check templated labels such as `ships-with:<group>` or `after:<key>`, which are created when used. Each missing label is a `warn` with the fix "run /kinetic:init to create it". Skip it for the local tracker. Never create anything.
3. Print the checks, including the `tracker`, `tracker-access` and `pr-template` entries, as a table (name, status, detail). Under it, list the one-line fix for each `warn` or `fail`. Then print the `guarantees` entries as an Enforced/Instructed table for the active harness — those marked Instructed hold only through skill text.
4. End with one line: all clear, or the count of warnings and failures.
