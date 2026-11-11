# Tracker adapter: local

Access: files only. No `tracker` key in settings means local. Tickets are readable markdown files at `<run_dir>/issues/NN-<repo>-<slug>.md`; kinetic state in the run directory is the source of truth, and the files are a view of it.

`python3 -m kinetic.board header --run <dir> --id <id>` owns each ticket file's header: its keys, order and format. Do not restate or edit the header by hand. Every write is two steps: update kinetic state (`python3 -m kinetic.state set-ticket` or `human-done`), then run `header` for that ticket and `python3 -m kinetic.board render --run <dir>` to refresh the table. `python3 -m kinetic.board drift --run <dir>` reports any difference between a file and state.

## Operations

### create slice parent
Create the slice folder `<run_dir>/issues/` and its `README.md` with `kinetic.board render`. The folder is the parent reference.

### create child
Record the ticket in state (the tickets phase writes it into the run's state), then `kinetic.board header` writes its file, then `kinetic.board render`.

### link blocker
Record `blocked_by` with its edge type in state, then `header` for the ticket.

### link after
Record `after` in state, then `header`.

### link ships-with
Record `ships_with` in state, then `header`.

### link related
Record `related` in state, then `header`.

### set kind
Record `kind` in state, then `header`.

### move status
Use `set-ticket` (or `human-done` for a human ticket), then `header` and `render`. A user may mark a human ticket done by editing its file; the drift check picks that up and asks before applying it.

### assign to user
Not stored. The assignee is derived by `header` from the kind (human: `you`, agent: `agent`); nothing to write.

### fetch
Read the ticket file in `<run_dir>/issues/`, or the ticket in state.

### comment
Append a line under a `Comments:` section at the end of the ticket file, below the header. `header` rewrites only the header, so comments are kept.

### ticket reference
The file name without extension, for example `01-api-add-endpoint`.

## Default names

```json
{
  "kind": {"agent": "kind:agent", "human": "kind:human"},
  "edge": {"snapshot": "edge:snapshot", "merge": "edge:merge", "release": "edge:release"},
  "after": "After:",
  "ships_with": "Ships with:",
  "related": "Related:",
  "status": {"todo": "todo", "running": "running", "done": "done", "merged": "merged", "blocked": "blocked"}
}
```
