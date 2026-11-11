# Tracker adapter: GitHub

Access: the `gh` CLI. Required setting: `github_repo` (`org/repo`), the one repo that holds every issue of the run, because a run spans several repos. Pass it as `--repo <github_repo>` on every call.

Label rule: before any `--label` or `--add-label`, check that the label exists with `gh label list --repo <github_repo>`. When one is missing, report it and ask the user (or point to /kinetic:init); never create a label silently with `gh label create`.

## Operations

### create slice parent
`gh issue create --repo <github_repo> --title ... --body ...`. Keep the issue number as the parent reference.

### create child
`gh issue create` as above, with the kind label. Attach it to the parent as a sub-issue. Sub-issue support depends on the installed `gh` version: confirm it (`gh issue --help`, `gh --version`) before relying on it. See Fallbacks.

### link blocker
Use the native "blocked by" relationship if the installed `gh` supports it. Also add the edge label (`names.edge.<snapshot|merge|release>`) to the blocked issue with `gh issue edit --add-label`. See Fallbacks.

### link after
Add a line `names.after` with `#n` substituted for the earlier issue's number to the body of the later issue (`gh issue edit --body`), keeping the rest of the body.

### link ships-with
Add the label `names.ships_with` with `<group>` substituted to every issue in the group.

### link related
Add a line `names.related` with `#n` substituted for the related issue's number to the body of the issue.

### set kind
Set the label `names.kind.agent` or `names.kind.human` with `gh issue edit --add-label` / `--remove-label`.

### move status
GitHub issues are only open or closed, so status is a label. Remove any other `names.status.*` label from the issue, then add the one named by `names.status.<role>`. For `todo`, `running` and `blocked`, also run `gh issue reopen` if the issue is closed. For `done` and `merged`, close it with `gh issue close`.

### assign to user
`gh issue edit <n> --repo <github_repo> --add-assignee @me`. Use it for human tickets.

### fetch
`gh issue view <n> --repo <github_repo>`: title, body, labels, state.

### comment
`gh issue comment <n> --repo <github_repo> --body ...`.

### ticket reference
`#n` inside `github_repo`, or `<github_repo>#n` from another repo's PR.

## Fallbacks

Where a native relationship (sub-issue, "blocked by") is missing in the installed `gh`, use the label or a body line instead: `Blocked by: #n` in the body, plus the edge label; for a sub-issue, a `Parent: #n` line in the child's body. Say so in the run log, naming the relationship and the fallback used. Do not invent `gh` subcommands.

## Default names

```json
{
  "kind": {"agent": "kind:agent", "human": "kind:human"},
  "edge": {"snapshot": "edge:snapshot", "merge": "edge:merge", "release": "edge:release"},
  "after": "After: #n",
  "ships_with": "ships-with:<group>",
  "related": "Related: #n",
  "status": {"todo": "To Do", "running": "In Progress", "done": "Done", "merged": "Done", "blocked": "Blocked"}
}
```
