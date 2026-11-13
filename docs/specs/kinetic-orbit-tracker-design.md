# Kinetic: Orbit as the ticket store

Status: draft for approval. Base: kinetic `ce59975`, Orbit `3f86fc4` (0.10.10, export `schema_version` 2). Builds on [kinetic-trackers-human-tickets-pr-template-design.md](kinetic-trackers-human-tickets-pr-template-design.md).

This change spans two repositories. Part 1 (Orbit) is filed in the Orbit repository with its own ADR and glossary entries, and released first. Part 2 (kinetic) is built here and depends on that release. Part 1 must make sense to a reader who has never heard of kinetic. That is why it uses only Orbit's vocabulary, and why its examples name no kinetic concept.

## Why

Kinetic and Orbit have the same owner, and they fit together naturally: Orbit is a Git-native Board of Tasks for Agents, and kinetic produces a graph of tickets for agents. Today kinetic can only reach Orbit through the `other` tracker adapter, as prose that the agent follows one CLI call at a time. Every tracker kinetic supports keeps two copies of each ticket: kinetic's `state.json` is the truth, and the tracker is a mirror. Mirrors drift (kinetic already needs `kinetic board drift` for the local tracker), and every write costs extra calls.

The goal is one copy. With `tracker: orbit`, a run's tickets live as Tasks on an Orbit Board, and kinetic reads and writes them there. Kinetic still decides what runs and when. Orbit holds the Tasks and keeps them consistent.

## Goals

1. **One source of truth for tickets.** With the Orbit tracker, ticket data lives only on the Orbit Board. Nothing is mirrored, so nothing can drift.
2. **Kinetic keeps scheduling.** The frontier, edge types (`snapshot`, `merge`, `release`), the parallel cap, fix rounds and the merge pipeline stay in kinetic and behave exactly as they do today.
3. **Efficient.** Decompose writes a whole run's tickets in one Orbit call and one commit. Each scheduling step reads the run's tickets in one Orbit call.
4. **Robust.** Multi-step writes are atomic. Retrying after a crash creates no duplicates. Other Agents on the same Board cannot claim a kinetic ticket.
5. **Stuck implementers are visible.** Each running ticket shows whether its implementer is still alive.
6. **Visible outside kinetic.** `orbit tree`, `orbit list` and `orbit show` show a run's progress. People finish human tickets with plain `orbit` commands.

## Non-goals

- Orbit scheduling kinetic's work. Kinetic never uses `orbit ready` to choose tickets.
- Edge types in Orbit. Orbit keeps one kind of Dependency. Kinetic records its edge types in its own Annotation.
- Claims without a Lease in Orbit.
- Routing GitHub, Jira or Linear through Orbit's Remote Trackers. Those tracker adapters stay as they are.
- Switching a run to another tracker mid-run.
- Moving run-level state (phase, repos, verify records, worktrees, owner session) out of `state.json`.

## Anti-goals

These would make the change a failure even if it works:

- **Kinetic gets worse without Orbit.** The `local`, `github`, `jira`, `linear` and `other` trackers behave exactly as before, step for step, and Orbit is never a required install.
- **Kinetic's core knows Orbit.** Only the Orbit ticket store and `trackers/orbit.md` may name Orbit commands or concepts. The frontier, graph, status, hooks and skills talk to the ticket store interface only.
- **Orbit becomes a kinetic plug-in.** Every Orbit addition has a use without kinetic, its own tests, and no kinetic vocabulary in Orbit's code, docs, glossary or examples.
- **Two copies again.** Kinetic does not cache Orbit Tasks in `state.json`.

## Approaches considered

1. **Kinetic owns tickets, Orbit mirrors them** through a sync command. Robust and cheap, but it keeps two copies, so drift is still possible, and Orbit is only a view.
2. **Orbit owns tickets and scheduling.** Kinetic's frontier calls `orbit ready --claim`. One source of truth, but it rewrites kinetic's scheduling core, loses edge types, and ties a long implementer run to Orbit's Lease timing.
3. **A prose tracker adapter only,** like `trackers/github.md`. The least code, but the most agent calls, and the least robust.
4. **Orbit holds tickets, kinetic schedules (chosen).** Orbit gains two general features: Batches and Annotations. Kinetic gains a ticket store interface with a local implementation and an Orbit implementation. One copy, no change to scheduling logic, and both tools stay general.

An earlier version of option 4 also added typed edges and Claims without a Lease to Orbit. Both were dropped: kinetic's edge types fit in its own Annotation (see "Mapping"), and Claims without a Lease would weaken Orbit's main safety net for every other Agent.

## Vocabulary

Each tool keeps its own words. This table is the only place where they meet, and the Orbit ticket store is the only code that translates between them.

| Concept | kinetic term | Orbit term |
|---|---|---|
| one unit of work | ticket | Task (a SubTask, here) |
| a group of tickets | slice | Parent Task with Type `epic` |
| a ticket that must finish first | blocker (`blocked_by`, with an edge type) | Dependency |
| exclusive ownership while working | running ticket | Claim, valid during its Lease |
| owner of the work went silent | stuck implementer | Stale |
| waiting for a person's decision | `needs_decision`, `blocked` status | Waiting (`waiting_on`) |
| keep a ticket away from other agents | (implicit: only kinetic dispatches) | Hold Label |
| tool-owned data on a ticket | ticket fields | Annotation (new) |
| several changes landing together | one state mutation | Batch (new) |
| retry-safe identity before an ID exists | provisional ticket id | Source Key (new) |

Words that look alike but mean different things:

- Kinetic's **`blocked` status** (a running ticket that needs help) is not Orbit's **Blocked** (a derived condition: an unfinished Dependency). Kinetic `blocked` maps to Orbit Waiting.
- Kinetic's **"Waiting on you"** (human tickets a person can act on now) is not Orbit's **Waiting** (any Task stuck on something outside the graph).
- Kinetic's **`kinetic board`** (the local ticket files view) is not Orbit's **Board**. This doc always writes "Orbit Board" for the latter.
- Kinetic's **claim** of a run by a session (`hooks/claim_run.py`) is not an Orbit **Claim**.
- Orbit's glossary avoids **namespace** (it means Slug there), **store** (for the Board), **client** (for Agent) and **blocker** (for Dependency). Part 1 uses none of them.
- Kinetic's glossary avoids **adapter** unqualified. Part 2 says "tracker adapter" for the prose files and "ticket store" for the new interface.

## Part 1: Orbit changes

Two general features. Both get an ADR and glossary entries in the Orbit repository, CLI and MCP parity (per ADR 0004, each new command is also an MCP tool), and an export `schema_version` bump.

### Batch: `orbit batch`

**Batch** (new glossary term): a list of Task operations that Orbit applies under one Board lock and publishes as one commit. Either every operation applies or none does.

- `orbit batch --file <path>` (or `-` for stdin), with `--dry-run` to validate without writing, like `orbit migrate`. The command is called `batch` rather than `apply`, because `--apply` already means "run the previewed change" in `migrate`, `triage` and `remote`.
- **Operations:** `add`, `update`, `label`, `depend`, `undepend`, `claim`, `heartbeat`, `release`, `done`, `cancel`, `reopen`, `comment`, `annotate`. Each takes the same fields and follows the same rules as its command.
- **Source Key** (new glossary term): an optional caller-chosen string on `add` that names the Task in the system that asked for it. Later operations in the same Batch can refer to the Task by Source Key instead of Task ID. Orbit stores the Source Key on the Task and returns it in `show`, `list` and `export`. An `add` whose Source Key already exists on the Board matches that Task instead of creating another, so a retried Batch creates no duplicates. A Source Key is unique per Board.
- **Output:** one JSON object with the Source Key to Task ID map, the result of each operation, and whether a commit was made (`committed`; Orbit's commit API returns no hash). On failure nothing is written, and the error names the failing operation's index and code.

Uses: importing a plan document as Tasks, a planning skill filing a Parent Task with its SubTasks and Dependencies, migrating from another tracker, and reserving Tasks for one orchestrating Agent (remove a Hold Label and Claim in one step, so no other Agent can claim in between).

### Annotation: `orbit annotation`

**Annotation** (new glossary term): structured data that one tool attaches to a Task under the tool's name. Orbit stores, returns and shows it, but never interprets it: an Annotation never affects Ready, Blocked, Claim eligibility or Status. _Avoid_: metadata, custom field, namespace, extra.

- Stored in the Task frontmatter as `annotations: {<owner>: <JSON object>}`. The **owner** is a lowercase slug naming the tool, for example `ci` or `planner`.
- `orbit annotation set <id> <owner> --value <object>` replaces that owner's Annotation (`--json` is Orbit's global output flag, so the value has its own option). `orbit annotation remove <id> <owner>` deletes it. Both are also Batch operations (`annotate`).
- Returned in `show --json`, `list --json` and `export`. Today unknown frontmatter fields survive a round trip, but no JSON output returns them.
- Shown in human `orbit show` output, one line per owner, so no data is hidden.
- Capped in size per owner (Orbit's call; 8 KiB is a reasonable default). `orbit doctor` reports Annotations that are not JSON objects.
- Never pushed to or pulled from a Remote Tracker, for the same reason ADR 0013 keeps Checkpoints local.

Uses: CI results on a Task, another orchestrator's bookkeeping, links to systems no Remote Tracker covers.

## Part 2: kinetic changes

### Ticket store

**Ticket store** (new kinetic glossary term): where a run's tickets live, behind one interface. _Avoid_: adapter, backend, Board.

`state.py` gets the interface. Two implementations:

- **Local ticket store:** today's behavior, extracted unchanged. Tickets stay in `state.json` under `tickets`. Used by every tracker except `orbit`.
- **Orbit ticket store:** tickets as Tasks on an Orbit Board, as described in "Mapping".

The interface, in kinetic's terms only:

- **read:** every ticket of the run, staged ones included, in one call.
- **write:** a batch of ticket changes that applies fully or not at all.
- **stage** and **publish:** see "Decompose flow".
- **touch:** signal that a running ticket's implementer is alive.
- **liveness:** for a running ticket, `alive`, `stuck` or `unknown`.
- **health:** the doctor checks this implementation needs, each with a status and a one-line fix.

The local ticket store writes on `stage` exactly as `set-ticket` does today, treats `publish` and `touch` as no-ops, answers `unknown` for liveness, and has no health checks. Kinetic shows `unknown` as nothing, so local runs look as they do today.

Comments stay a tracker adapter operation, as today: the local tracker adapter writes them into the ticket file, and `trackers/orbit.md` uses `orbit comment add`.

`state.load` fills `state["tickets"]` from the run's ticket store, and `state._mutate` sends ticket changes back through it. So the modules that read `state["tickets"]` today (`board.py`, `frontier.py`, `gitops.py`, `graph.py`, `next_step.py`, `status.py`) read through the interface without changing. Validation (`STATUSES`, `EDGE_TYPES`, `KINDS`, `_check_fields`, `done_refusal`, the human-done rule) stays in `state.py` and runs before any implementation writes.

The ticket store is chosen in one place, from the tracker: `orbit` selects the Orbit ticket store, and every other tracker selects the local one. It is recorded in `state.json` at intake as `{"ticket_store": {"kind": "orbit", "config": {...}}}`. Only the chosen implementation reads `config`, so the Orbit Board path never appears in kinetic's core.

### The `orbit` tracker adapter

- `orbit` is added to `TRACKERS` in `scripts/kinetic/tracker.py`. It has no required settings. An optional `orbit_dir` setting names the Orbit Board when it cannot be found from the run's repos.
- `trackers/orbit.md` is the tracker adapter. Most operations are one line: the ticket work is done by `kinetic state` commands, which write through the ticket store. "Ticket reference" is the Task ID.
- Its default names block maps the roles as in "Mapping", and adds two Orbit-only roles: `hold` (default `kinetic`) and `run` (default `kinetic-run-<run id>`). Every Label kinetic writes comes from these names, so a Board with other conventions overrides them in `tracker_names`.
- `/kinetic:init` offers the `orbit` tracker when an `orbit` binary and an Orbit Board are found.

### Liveness hook

Kinetic's existing PostToolUse hooks (`record_edit.py` after edits, `claim_run.py` after shell commands) also call the run's ticket store `touch`, at most once every 5 minutes per worktree (a stamp file in the run directory, keyed by the enclosing git checkout and checked before any ticket read, so most tool calls cost one file check). Reusing them means no harness installer changes. The hook finds the ticket whose worktree contains the tool call's working directory. It never blocks the tool call, and a failed touch is logged, not raised. The hook does not know which ticket store is in use.

The Orbit ticket store implements `touch` as an Orbit heartbeat by the run's Claim holder, and reports `stuck` when that Claim is Stale. `kinetic status` shows a `stuck` running ticket as "implementer may be stuck". Kinetic does not act on it automatically.

### Doctor

Doctor adds the chosen ticket store's health checks to its table, and stays unaware of Orbit itself. The Orbit ticket store's checks: the `orbit` binary exists and has Batches (`orbit batch --help` succeeds), and `export` returns the pinned `schema_version` (3); an Orbit Board is found; and the Board lists `names.hold` in `non_ready_labels`. Each failing check prints a one-line fix. Other trackers use the local ticket store, which adds no checks.

### Tests

- One contract test suite for the ticket store interface runs against both implementations.
- Orbit ticket store tests create a temporary Orbit Board with the real `orbit` binary. They are skipped, with a visible reason, when `orbit` is not installed.
- Hook tests cover the 5-minute throttle and a failing touch, with a fake ticket store.
- All existing tests pass unchanged against the local ticket store.
- A test fails if any file mentions `orbit` other than the Orbit ticket store module, `trackers/orbit.md`, the tracker registry in `tracker.py`, the init skill and the docs. That enforces the second anti-goal.

## Mapping (Orbit ticket store only)

| kinetic | Orbit |
|---|---|
| slice | Parent Task with Type `epic` |
| ticket | SubTask of its slice's Parent Task |
| ticket id | Task ID |
| provisional ticket id | Source Key `kinetic:<run id>:<provisional id>` |
| all ticket fields | Annotation owned by `kinetic`, which is authoritative |
| `repo` | Annotation (setting the Task's Repository field is left for later) |
| `blocked_by` (any edge type) | Dependency, plus `{id, type}` in the Annotation |
| `after`, `related`, `produces`, `consumes`, `branch`, `report`, `snapshot_published`, `human_note`, `done_by` | Annotation only |
| `ships_with` | Annotation, plus the Label `names.ships_with` |
| `kind: human` | Label `names.kind.human` (default `ready-for-human`, already a default Hold Label) |
| ticket body (What to build, Interfaces, Acceptance criteria) | Task body |
| run membership | Label `names.run` on every Task of the run |

Kinetic's edge types are safe on top of one Orbit Dependency kind. Every kinetic edge is satisfied no earlier than when the blocker is Done. Orbit refuses to Claim or complete a Task with an unfinished Dependency. So Orbit's rule never blocks something kinetic would allow, and kinetic adds the stricter checks for `merge` and `release`.

### Status

The Annotation holds kinetic's exact status. The Orbit Status, Claim, Waiting and Labels are derived from it and written in the same Batch.

| kinetic status | Orbit Status | Claim | Waiting | Hold Label `names.hold` |
|---|---|---|---|---|
| `todo` (agent) | `todo` | none | no | yes |
| `todo` (human) | `todo` | none | no | no (`names.kind.human` holds it) |
| `running` | `in_progress` | held by `kinetic-<run id>` | no | no |
| `needs_decision`, `blocked` | `in_progress` | kept (it may go Stale) | yes, with the reason | no |
| `done`, `done_with_concerns` | `done` | released by `done` | no | no |
| `merged`, `released` | `done` | none | no | no |

- **The Hold Label** keeps other Agents' `orbit ready --claim` away from kinetic's agent tickets while they are `todo`. Kinetic removes it and Claims in one Batch when it dispatches a ticket. An `in_progress` Task is never Ready, so it needs no Hold Label. Only an explicit `orbit claim --steal` can take it.
- **Resuming** a `needs_decision` or `blocked` ticket clears Waiting and renews the Claim by the same holder in the Batch that sets `running`. Liveness reports `stuck` only for `running` tickets.
- **Slice Parent Tasks** are closed by kinetic with `done`, in the same Batch that completes their last open SubTask.
- **Human tickets** are finished with `orbit done <id>`, which works on an unclaimed Task. When a read shows a human ticket that is Done in Orbit while its Annotation status is still `todo`, the read records `status: done` and `done_by: human` in one Batch.
- **An agent ticket marked Done outside kinetic** has no passing verify, so kinetic does not treat it as done. The read sets it to `needs_decision` with the note "marked done outside kinetic".

### Reads and writes

- **Orbit Board:** resolved on the ticket store's first use, because a run may have no repos at intake. It comes from `orbit_dir`, else Orbit's own discovery from the first repo, and is stored in the ticket store `config`. Every call passes `--dir`, so the result never depends on the current directory.
- **Read:** `orbit list --json --include-closed --label <names.run>`, once per scheduling step. Each Task carries its Annotations.
- **Write:** each kinetic write is one `orbit batch`. On a lock timeout the ticket store retries with backoff (three tries), and then fails the command with nothing written.

### Decompose flow

Today decompose calls `kinetic state set-ticket` once per ticket, then `kinetic graph validate`, and fixes tickets until validation passes. Writing each attempt to the Orbit Board would leave invalid graphs on it and cost one commit per ticket. So the interface separates staging from publishing:

1. Decompose stages tickets with the same `set-ticket` command, with provisional ids (`NN-<repo>-<slug>`, as in local mode). The Orbit ticket store keeps staged tickets in `<run_dir>/tickets.staged.json`. The local ticket store writes `state.json` as today.
2. `graph validate` and `graph topo` read through the interface, so they see staged tickets. They are unchanged.
3. Recording the approved breakdown gate publishes, and `kinetic state publish-tickets --run <dir>` publishes on demand. The Orbit ticket store sends every staged ticket in one Batch with Source Keys, records the Task IDs from the returned map (the slices in `state.json`; ticket references are rewritten on every read from each Task's Source Key, so the Annotation may still hold provisional ids), and deletes the staged file and the published ticket files under `<run_dir>/issues/`. Each ticket's body comes from its file. The local ticket store does nothing.
4. Tickets added later (a new slice, a split ticket) go through the same stage and publish. Source Keys make a repeated publish safe after a crash.

## Constraints

- Orbit commits on every write when `auto_commit = true`. Batches keep that to one commit per kinetic write. Heartbeats change only the Lease, so they create no commits.
- Kinetic pins Orbit's export `schema_version` and checks for the `batch` command in doctor, rather than a version number.
- The Board's `lease_minutes` (30 by default) must stay well above the 5-minute touch interval.
- Kinetic never edits Orbit Task files directly. Every change goes through the `orbit` CLI.
- Checked on Orbit 0.10.10 with a throwaway Board: `kinetic-<run id>` is accepted as a Claim holder, `waiting_on` can be set on an `in_progress` Task while its Claim stays, a heartbeat reports `committed: false`, and `orbit done` works on an unclaimed Task.

## Decided

- Option 4: Orbit holds tickets, kinetic schedules.
- Orbit gains only Batches (with Source Keys) and Annotations. No typed edges, no Claims without a Lease.
- Kinetic's core talks to a ticket store interface. Only the Orbit ticket store and its tracker adapter know Orbit.
- GitHub, Jira and Linear stay on their own tracker adapters. Orbit stays optional.

## Calls made while writing (check these)

- New Orbit terms: Batch, Source Key, Annotation (with owner). New kinetic term: ticket store. Command names `orbit batch` and `orbit annotation set|remove`.
- Kinetic `needs_decision` and `blocked` map to Orbit Waiting, so a person reading the Orbit Board sees why the Task is paused.
- Label names come from the tracker adapter's names block (`hold`, `run`, `kind.human`, `ships_with`) and can be overridden.
- Claim holder `kinetic-<run id>`. Run ids are 12 hex characters, so they are valid in Labels.
- Touch at most every 5 minutes. A `stuck` running ticket is reported, never acted on.
- The Annotation is authoritative; Orbit Status, Claim, Waiting and Labels are derived from it.
- Spec location: `docs/specs/`, following this repo's convention.

## Left to the builder

- The exact JSON shape of `orbit batch` input and output, following Orbit's existing `--json` envelope.
- The Annotation size cap and how Source Keys are stored and indexed in Orbit.
- How the ticket store interface is split into functions, as long as validation stays in `state.py`.
