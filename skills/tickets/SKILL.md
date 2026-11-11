---
name: tickets
description: Break the approved spec into vertical slices (parent tickets) and per-repo child tickets with typed blocking edges, publish them, and record them in run state. Use at the tickets phase of a kinetic run.
model: opus
---

# Tickets

Break the spec into **slices** (tracer-bullet vertical slices, each a parent ticket) and, per slice, one **child ticket per repo** it touches. The child ticket is the unit an agent implements; the slice stays the unit you demo and verify. This skill never invokes another skill.

The orchestrator passes `Run: <dir>` (the run directory, `<workspace>/<run-id>/`), the spec location and the list of repos in play. Run scripts as `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.<module> ...`.

Tracker settings come from the run: `tracker: jira|local` in `~/.config/kinetic/` config (set by `/kinetic:init`). When no tracker is configured, use local mode.

## Process

### 1. Gather context

Read the spec in full (Jira issue or `<run_dir>/spec.md`) and the repos list. Explore the codebase if you haven't. Use `GLOSSARY.md` vocabulary and respect ADRs in the areas touched. Look for prefactoring that makes the change easy first: "make the change easy, then make the easy change."

### 2. Draft slices and child tickets

<vertical-slice-rules>

- Each slice cuts a narrow but COMPLETE path through every layer (schema, API, UI, tests): vertical, NOT a horizontal slice of one layer.
- A completed slice is demoable or verifiable on its own.
- Each child ticket is sized to fit in a single fresh context window and touches exactly one repo.
- Any prefactoring is done first.

</vertical-slice-rules>

Give each child ticket its **blocking edges**, each with a type:

- `snapshot`: downstream may start once upstream has a snapshot build and is pinned.
- `merge`: downstream waits for the upstream merge.
- `release`: downstream waits for a released version.

Use only these three types. A ticket with no blockers can start immediately. Prefer `snapshot` across repos when the upstream can publish one; use `merge` or `release` only when the downstream genuinely cannot proceed earlier.

**Wide refactors are the exception to vertical slicing.** One mechanical change (rename a column, retype a shared symbol) whose blast radius fans across the codebase cannot land green as a single slice. Sequence it as expand-contract: expand (add the new form beside the old), migrate call sites in batches sized by blast radius (each batch its own ticket blocked by the expand), then contract (delete the old form, blocked by every migrate batch).

### 3. Quiz the user

Present the breakdown as a numbered list. For each ticket show the title, its slice and repo, **Blocked by** (with edge types), and what it delivers end to end. Ask:

- Does the granularity feel right (too coarse / too fine)?
- Does each ticket depend only on tickets that genuinely gate it, with the right edge type?
- Should any tickets be merged or split further?

Iterate until the user approves.

### 4. Publish

Publish in dependency order (blockers first) so edges can reference real identifiers. Do NOT close or modify the source spec issue.

- **Jira**: create one parent issue per slice, and one child issue per repo under it. Link blockers with the native "blocks" link and add the label `edge:snapshot`, `edge:merge` or `edge:release` matching the edge type. Use the ticket key as the ticket id.
- **Local**: write one file per child ticket at `<run_dir>/issues/NN-<repo>-<slug>.md`, numbered from `01` in dependency order. Use `NN-<repo>-<slug>` as the ticket id. One ticket per file, never a combined file.

Local ticket template:

```md
# <NN>: <Ticket title>

**Slice:** <slice id>
**Repo:** <repo>
**What to build:** the end-to-end behaviour this ticket makes work, from the user's perspective, not a layer list.
**Blocked by:** `<ticket id>` (snapshot|merge|release), ... or "None (can start immediately)".

- [ ] Acceptance criterion 1
- [ ] Acceptance criterion 2
```

Jira issue bodies use the same content (Parent, What to build, Acceptance criteria). Avoid file paths and code snippets; they go stale. Exception: inline a prototype's decision-rich snippet (state machine, schema, type shape) and say it came from a prototype.

### 5. Record in state

Ids: a ticket id is the Jira key in jira mode and `NN-<repo>-<slug>` in local mode; a slice id follows the same rule for its parent ticket (Jira key, or `NN-<slug>` for a local parent).

First record the approved slice ids, before any child ticket, so `graph validate`'s slice check is live:

```
python3 -m kinetic.state set-slices --run <dir> --slices '["<slice-id>","<slice-id>"]'
```

Then, for every child ticket (`blocked_by` is a JSON list of `{"id","type"}`; use `[]` when none):

```
python3 -m kinetic.state set-ticket --run <dir> --id <ticket-id> --field repo=<repo> --field slice=<slice-id> --field 'blocked_by=[{"id":"<blocker-id>","type":"snapshot"}]'
```

Every slice id passed to `set-slices` must appear in at least one ticket's `slice` field. Do not edit `state.json` by hand.

### 6. Validate

```
python3 -m kinetic.graph validate --run <dir>
```

It prints `{"errors": [...]}` and exits non-zero on errors (missing repo, unknown blocker, invalid edge type, cycle). Fix the tickets (re-run `set-ticket` and update the tracker) and re-run until `errors` is empty. Then print the build order with `python3 -m kinetic.graph topo --run <dir>`.

The orchestrator runs the breakdown approval gate; do not set phases or gates here.

Adapted from mattpocock/skills (to-tickets), MIT License.
