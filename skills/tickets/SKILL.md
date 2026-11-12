---
name: tickets
description: Break the approved spec into vertical slices (parent tickets) and per-repo child tickets with typed blocking edges, publish them, and record them in run state. Use at the tickets phase of a kinetic run.
model: sonnet
---

# Tickets

Break the spec into **slices** (tracer-bullet vertical slices, each a parent ticket) and, per slice, one **child ticket per repo** it touches. The child ticket is the unit an agent implements; the slice stays the unit you demo and verify. This skill never invokes another skill.

The orchestrator passes `Run: <dir>` (the run directory, `<workspace>/<run-id>/`), the spec location and the list of repos in play. Run scripts as `kinetic <module> ...`.

Resolve the tracker with `kinetic tracker resolve` (set by `/kinetic:init`; with no tracker configured it resolves to local), read the adapter file it names, and follow its operations by name ("create slice parent", "create child", "link blocker", "link after", "link ships-with", "link related", "set kind", "assign to user", "fetch", ...). Tracker-specific names come from the resolve output: `names.kind.human`, `names.edge.<type>`, `names.after`, `names.ships_with`, `names.related`. Do not hard-code them.

## Process

### 1. Gather context

Read the spec in full (the tracker issue, fetched through the adapter's "fetch" operation, or `<run_dir>/spec.md`) and the repos list. Explore the codebase if you haven't. Use `<run_dir>/docs/GLOSSARY.md` (or the repo's own) vocabulary and respect ADRs in the areas touched. Look for prefactoring that makes the change easy first: "make the change easy, then make the easy change."

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

Beyond blockers, a child ticket may carry soft links, each only where it applies:

- `After`: soft precedence, "do this later if it is cheap" (not a blocker; it only breaks ordering ties).
- `Ships with`: a group name shared by tickets in different repos whose PRs must merge together.
- `Related`: tickets worth reading together, with no ordering.

Give each child a **Type**: `agent` (an implementer can do it) or `human` (only a person can: credentials, an infra apply, manual config, a decision, a console click). Propose the type and a one-line reason for every human ticket.

Use only these three edge types. A ticket with no blockers can start immediately. Use a `snapshot` edge between two repos only when the upstream repo's config has `publish_snapshot` and the downstream repo's has `pin` (read `~/.config/kinetic/repos.json` and each repo's `.kinetic.json`); without them the pin step cannot run and the downstream ticket never becomes ready, so use `merge`. Use `release` only when the downstream genuinely needs a released version: the orchestrator marks it released by hand, so say so in the ticket. Within one repo prefer `merge`.

Give each agent ticket its **interfaces** (human tickets have none): what it `produces` that another ticket uses (an API endpoint, a client method, an event, a schema, a config key), and what it `consumes` from other tickets or from existing code. Use one stable name per interface across tickets, in the glossary's terms (for example `StatementClient.export` or `event:statement-exported`). A ticket that consumes what another ticket produces must be blocked by it, directly or through other tickets; `graph validate` reports it as an error otherwise.

**Wide refactors are the exception to vertical slicing.** One mechanical change (rename a column, retype a shared symbol) whose blast radius fans across the codebase cannot land green as a single slice. Sequence it as expand-contract: expand (add the new form beside the old), migrate call sites in batches sized by blast radius (each batch its own ticket blocked by the expand), then contract (delete the old form, blocked by every migrate batch).

### 3. Quiz the user

Present the breakdown as a numbered list. Show a table with a `type` column, human tickets first, with a one-line reason under each human ticket. For each ticket show the title, its type, slice and repo (human tickets may have no repo), **Blocked by** (with edge types), **After** / **Ships with** / **Related** where they apply, **Interfaces** (produces / consumes, agent tickets only), and what it delivers end to end. Ask:

- Does the granularity feel right (too coarse / too fine)?
- Does each ticket depend only on tickets that genuinely gate it, with the right edge type?
- Should any tickets be merged or split further?

Iterate until the user approves.

### 4. Publish

Publish in dependency order (blockers first) so edges can reference real identifiers. Do NOT close or modify the source spec issue.

- **Tracker with remote issues**: follow the adapter: "create slice parent" per slice, "create child" per ticket under it, "set kind" for human tickets, "assign to user" for human tickets, "link blocker" with the edge type for each blocker, and "link after" / "link ships-with" / "link related" where they apply. Use the ticket reference the adapter gives as the ticket id.
- **Local**: write one file per child ticket at `<run_dir>/issues/NN-<repo>-<slug>.md`, numbered from `01` in dependency order. Use `NN-<repo>-<slug>` as the ticket id (a human ticket with no repo: `NN-<slug>`). One ticket per file, never a combined file. The first lines of the file are a header that `kinetic.board` owns (see step 5): write the template, then let `board header` fill it.

Local ticket template:

```md
# <NN>: <Ticket title>

**What to build:** the end-to-end behaviour this ticket makes work, from the user's perspective, not a layer list.
**Interfaces:** produces `<name>`, ...; consumes `<name>`, ... (or "none"). Omit for a human ticket.

- [ ] Acceptance criterion 1
- [ ] Acceptance criterion 2
```

The template carries no Status, Type, Repo, Slice, Blocked by, After, Ships with, Related or Assignee lines: `board header` inserts those owned lines from state, whose values you pass with `set-ticket` (step 5). Do not hand-write them. A human ticket's body is a checklist of the manual steps (`- [ ] step`) and the expected outcome of each, with no Interfaces section. A human ticket with no checklist of manual steps (or acceptance criteria) is an error: fix it before the breakdown gate. Remote issue bodies use the same content (Parent, What to build, Interfaces, Acceptance criteria). Avoid file paths and code snippets; they go stale. Exception: inline a prototype's decision-rich snippet (state machine, schema, type shape) and say it came from a prototype.

### 5. Record in state

Ids: a ticket id is the adapter's ticket reference for a remote tracker and `NN-<repo>-<slug>` in local mode; a slice id follows the same rule for its parent ticket (the reference, or `NN-<slug>` for a local parent).

First record the approved slice ids, before any child ticket, so `graph validate`'s slice check is live:

```
kinetic state set-slices --run <dir> --slices '["<slice-id>","<slice-id>"]'
```

Then, for every child ticket (`blocked_by` is a JSON list of `{"id","type"}`; use `[]` when none):

```
kinetic state set-ticket --run <dir> --id <ticket-id> --field repo=<repo> --field slice=<slice-id> --field 'blocked_by=[{"id":"<blocker-id>","type":"snapshot"}]' --field 'produces=["<name>"]' --field 'consumes=["<name>"]'
```

Omit `produces` or `consumes` when the ticket has none. Add the new fields where they apply: `--field kind=human` (human ticket; leave out `repo` when it has none), `--field 'after=["<id>"]'`, `--field ships_with=<group>`, `--field 'related=["<id>"]'`.

In local mode, after writing each ticket file run `kinetic board header --run <dir> --id <ticket-id>` so its header matches state, and when all files are written `kinetic board render --run <dir>`. Do this before anything reads `board drift`: a hand-written file shows drift until its first `header`.

Every slice id passed to `set-slices` must appear in at least one ticket's `slice` field. Do not edit `state.json` by hand.

### 6. Validate

```
kinetic graph validate --run <dir>
```

It prints `{"errors": [...], "warnings": [...]}` and exits non-zero on errors (missing repo, unknown blocker, invalid edge type, cycle, a consumer with no edge to the ticket producing what it consumes). Warnings name interfaces that no ticket produces: confirm each already exists in the code, or add the missing ticket. Fix the tickets (re-run `set-ticket` and update the tracker) and re-run until `errors` is empty. Then print the build order with `kinetic graph topo --run <dir>`.

The orchestrator runs the breakdown approval gate; do not set phases or gates here.

Adapted from mattpocock/skills (to-tickets), MIT License.
