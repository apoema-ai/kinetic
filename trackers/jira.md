# Tracker adapter: Jira

Access: the Atlassian MCP. Required settings: `jira_project`, `slice_issue_type`, `child_issue_type`. Use the tool names the installed MCP actually lists (discover them first); do not guess.

## Operations

### create slice parent
Create an issue of `slice_issue_type` in `jira_project` with the slice title and spec summary. Keep its key as the parent reference.

### create child
Create an issue of `child_issue_type` in `jira_project` with the parent set to the slice parent. Add the kind label (`names.kind.<kind>`).

### link blocker
Create a native "Blocks" issue link from the blocker to the blocked ticket. Add the edge label (`names.edge.<snapshot|merge|release>`) to the blocked ticket, since the native link carries no edge type.

### link after
Soft precedence has no native link. Add the label `after:<key>` to the ticket that comes later.

### link ships-with
Add the label `ships-with:<group>` to every ticket in the group.

### link related
Create a native "Relates to" issue link between the two tickets.

### set kind
Set the label `names.kind.agent` or `names.kind.human`; remove the other one.

### move status
Transition the issue to the workflow status named by `names.status.<todo|running|done|merged|blocked>`. List the available transitions first; if the named one is missing, tell the user and stop.

### assign to user
Assign the issue to the current user (from the MCP's user-info call). Use it for human tickets.

### fetch
Read the issue by key: summary, description, status, labels, links.

### comment
Add a comment to the issue by key.

### ticket reference
The issue key (for example `INV-123`) in PR bodies; link it with the site's browse URL when known.

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
