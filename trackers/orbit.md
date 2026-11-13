# Tracker adapter: Orbit

Access: the `orbit` CLI, always with `--json` and `--dir <anchor>`. Optional setting: `orbit_dir` (`tracker_settings.orbit_dir`), the Board anchor or Board folder, for when the Board cannot be found from the run's first repo. The Orbit Board needs `names.hold` (default `kinetic`) in `non_ready_labels` in its `config.toml`; doctor checks it.

With this tracker the run's tickets live on the Orbit Board: the Orbit ticket store reads and writes them, and kinetic state is not a separate copy. This adapter publishes staged tickets: during decompose, follow the Local steps (ticket files and `NN-<repo>-<slug>` ids); when the breakdown gate is approved, kinetic publishes every staged ticket in one `orbit batch`, and from then on a ticket id is its Orbit Task ID.

Never edit Orbit Task files by hand, and never run `orbit ready --claim` for a kinetic ticket: kinetic schedules its own tickets.

A run whose ref is an existing Orbit Task (for example `/kinetic:implement orb-a7b2c9`) does not take that Task over: kinetic files its own slice and tickets for the run, and the original Task stays as the request. Link it from the tickets with `related` (or a comment) and close it yourself when the run ships.

After the breakdown gate, a ticket kinetic adds later (a `NEEDS_HUMAN` ticket, a review fix) goes to the Board in the same write that records it, and its provisional id keeps working with `kinetic state` commands.

## Operations

### create slice parent
Done by publishing: each slice becomes a Parent Task with type `epic`.

### create child
Record the ticket with `kinetic state set-ticket` (it is staged); publishing makes it a SubTask of its slice's Parent Task.

### link blocker
Record `blocked_by` with its edge type with `set-ticket`. The ticket store writes an Orbit dependency and keeps the edge type in the ticket's `kinetic` Annotation.

### link after
Record `after` with `set-ticket` (kept in the Annotation; no Orbit dependency).

### link ships-with
Record `ships_with` with `set-ticket`; the ticket store adds the label `names.ships_with`.

### link related
Record `related` with `set-ticket` (kept in the Annotation).

### set kind
Record `kind` with `set-ticket`; a human ticket carries the label `names.kind.human`.

### move status
Record `status` with `set-ticket` (or `human-done`); the ticket store derives the Orbit status, claim, waiting reason and labels in one batch.

### assign to user
Nothing to do: a human ticket is held by `names.kind.human`, and a person finishes it with `orbit done <id>`.

### fetch
`orbit show <id> --json --dir <anchor>`: title, body, labels, status, Annotations and comments.

### comment
`orbit comment add <id> --by kinetic-<run id> --body-file - --dir <anchor>`, with the comment on stdin.

### ticket reference
The Orbit Task ID, for example `orb-a7b2c9.d4b3df`.

## Default names

```json
{
  "kind": {"agent": "", "human": "ready-for-human"},
  "edge": {"snapshot": "", "merge": "", "release": ""},
  "after": "",
  "ships_with": "ships-with-<group>",
  "related": "",
  "status": {"todo": "todo", "running": "in_progress", "done": "done", "merged": "done", "blocked": "in_progress"},
  "hold": "kinetic",
  "run": "kinetic-run-<run id>"
}
```
