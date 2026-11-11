# Tracker adapter: other

For a tracker kinetic has no adapter for. Required: `tracker_description` in settings, the user's own prose on how to do each operation. Follow it exactly. When an operation is not covered by it, ask the user how to do it; do not guess a tool or an API.

## Operations

### create slice parent
As `tracker_description` says.

### create child
As `tracker_description` says; set the parent to the slice parent.

### link blocker
As `tracker_description` says, with the edge type (`snapshot`, `merge`, `release`).

### link after
As `tracker_description` says (soft precedence).

### link ships-with
As `tracker_description` says (tickets that ship together).

### link related
As `tracker_description` says.

### set kind
As `tracker_description` says (`agent` or `human`).

### move status
As `tracker_description` says, using `names.status.<role>`.

### assign to user
As `tracker_description` says.

### fetch
As `tracker_description` says.

### comment
As `tracker_description` says.

### ticket reference
As `tracker_description` says; ask the user if it names none.

## Default names

```json
{
  "kind": {"agent": "kind:agent", "human": "kind:human"},
  "edge": {"snapshot": "edge:snapshot", "merge": "edge:merge", "release": "edge:release"},
  "after": "after",
  "ships_with": "ships-with:<group>",
  "related": "relates to",
  "status": {"todo": "To Do", "running": "In Progress", "done": "Done", "merged": "Done", "blocked": "Blocked"}
}
```
