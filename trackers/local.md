# Tracker adapter: local

Access: files only. No `tracker` key in settings means local. Tickets are readable markdown files at `<run_dir>/issues/NN-<repo>-<slug>.md`; kinetic state in the run directory is the source of truth, and the files are a view of it.

Every write is two steps: update kinetic state (`python3 -m kinetic.state set-ticket` or `human-done`), then rewrite the file with `python3 -m kinetic.board header --run <dir> --id <id>` and refresh the table with `python3 -m kinetic.board render --run <dir>`. Never edit a header line by hand; `python3 -m kinetic.board drift --run <dir>` reports any difference between a file and state.

## Operations

### create slice parent
Create the slice folder `<run_dir>/issues/` (or the slice's own folder) and its `README.md` via `kinetic.board render`. The folder is the parent reference.

### create child
Record the ticket in state (the tickets phase writes it into the run's state), then `kinetic.board header --run <dir> --id <id>` writes `issues/NN-<repo>-<slug>.md`. Header order: `Status:`, `Type:`, `Blocked by:`, `After:`, `Ships with:`, `Related:`, `Assignee:`, `Labels:`. Then `kinetic.board render --run <dir>`.

### link blocker
Record `blocked_by` with its edge type in state; `header` writes `Blocked by: 01 (merge), 02 (snapshot)`.

### link after
Record `after` in state; `header` writes the `After:` line.

### link ships-with
Record `ships_with` in state; `header` writes the `Ships with:` line.

### link related
Record `related` in state; `header` writes the `Related:` line.

### set kind
Record `kind` in state; `header` writes the `Type:` line.

### move status
Use `set-ticket` (or `human-done` for a human ticket), then `header` and `render`. A user may mark a human ticket done by editing `Status: done`; the drift check picks that up and asks before applying it.

### assign to user
Set `Assignee:` through state; `header` writes it.

### fetch
Read the ticket file in `<run_dir>/issues/`, or the ticket in state.

### comment
Append a line under a `Comments:` section at the end of the ticket file. Comments are not part of the header and are never overwritten by `header`.

### ticket reference
The file name without extension, for example `01-api-add-endpoint`; use `tracker_description` if the user gave one, else this.

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
