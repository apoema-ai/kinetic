# Tracker adapter: GitHub

Access: the `gh` CLI. Required setting: `github_repo` (`org/repo`), the one repo that holds every issue of the run, because a run spans several repos. Pass it as `--repo <github_repo>` on every call.

## Operations

### create slice parent
`gh issue create --repo <github_repo> --title ... --body ...`. Keep the issue number as the parent reference.

### create child
`gh issue create` as above, with the kind label. Attach it to the parent as a sub-issue. Sub-issue support depends on the installed `gh` version: confirm it (`gh issue --help`, `gh --version`) before relying on it. See Fallbacks.

### link blocker
Use the native "blocked by" relationship if the installed `gh` supports it. Also add the edge label (`names.edge.<snapshot|merge|release>`) to the blocked issue with `gh issue edit --add-label`. See Fallbacks.

### link after
Add a line `After: #n` to the body of the later issue (`gh issue edit --body`), keeping the rest of the body.

### link ships-with
Add the label `ships-with:<group>` to every issue in the group. Create a missing label first with `gh label create` (check with `gh label list`).

### link related
Add a line `Related: #n` to the body of the issue.

### set kind
Set the label `names.kind.agent` or `names.kind.human` with `gh issue edit --add-label` / `--remove-label`.

### move status
Open the issue for `todo`, `running`, `blocked`: set a status label named by `names.status.<role>` (GitHub issues are only open or closed). Close it with `gh issue edit`/`gh issue close` for `done` and `merged`.

### assign to user
`gh issue edit <n> --repo <github_repo> --add-assignee @me`. Use it for human tickets.

### fetch
`gh issue view <n> --repo <github_repo>`: title, body, labels, state.

### comment
`gh issue comment <n> --repo <github_repo> --body ...`.

### ticket reference
`#n` inside `github_repo`, or `<github_repo>#n` from another repo's PR.

## Fallbacks

Where a native relationship (sub-issue, "blocked by") is missing in the installed `gh`, use the label or a body line instead: `Blocked by: #n` in the body, plus the edge label. Say so in the run log, naming the relationship and the fallback used. Do not invent `gh` subcommands.

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
