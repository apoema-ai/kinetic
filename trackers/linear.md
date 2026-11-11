# Tracker adapter: Linear

Access: the Linear MCP. Required setting: `linear_team`. Use the tool names the installed MCP actually lists; check its tool list before relying on any relation.

## Operations

### create slice parent
Create an issue in team `linear_team` with the slice title and spec summary. Keep its identifier as the parent reference.

### create child
Create an issue in the same team with the parent set to the slice parent (sub-issue), plus the kind label.

### link blocker
Create a "blocks" relation from the blocker to the blocked issue, if the MCP offers it. Also add the edge label (`names.edge.<snapshot|merge|release>`) to the blocked issue. See Fallbacks.

### link after
Soft precedence has no native relation. Add the label `after` followed by the identifier (for example `after:ENG-12`) to the later issue.

### link ships-with
Add the label `ships-with:<group>` to every issue in the group.

### link related
Create a "related" relation between the two issues, if the MCP offers it. See Fallbacks.

### set kind
Set the label `names.kind.agent` or `names.kind.human`; remove the other one.

### move status
Set the workflow state named by `names.status.<todo|running|done|merged|blocked>`. If the team has no state with that name, tell the user and stop.

### assign to user
Assign the issue to the current user. Use it for human tickets.

### fetch
Read the issue by identifier: title, description, state, labels, relations.

### comment
Add a comment to the issue.

### ticket reference
The issue identifier (for example `ENG-12`) in PR bodies, linked with its URL when the MCP returns one.

## Fallbacks

Where a native relation (blocks, related, sub-issue) is missing in the installed Linear MCP, use a label or a line in the description instead: `Blocked by: ENG-n`, `Related: ENG-n`, plus the edge label. Say so in the run log, naming the relation and the fallback used.

## Default names

```json
{
  "kind": {"agent": "kind:agent", "human": "kind:human"},
  "edge": {"snapshot": "edge:snapshot", "merge": "edge:merge", "release": "edge:release"},
  "after": "after",
  "ships_with": "ships-with:<group>",
  "related": "related",
  "status": {"todo": "Todo", "running": "In Progress", "done": "Done", "merged": "Done", "blocked": "Blocked"}
}
```
