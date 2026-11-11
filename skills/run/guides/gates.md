# Gates

Three gates: `spec`, `breakdown`, `ship`. Each asks with AskUserQuestion, then records the answer:

```
python3 -m kinetic.state record-gate --run <run_dir> --gate <spec|breakdown|ship> --approved <true|false> --note "<user's words or empty>"
```

A rejected gate: record `--approved false` with the reason as `--note`, `set-phase` back to the previous phase (spec gate to `grill` or `spec`, breakdown gate to `tickets`, ship gate to `review`), and re-read and follow that phase skill with the user's feedback. Then ask again. Never advance past an unapproved gate.

## Spec gate (after the spec phase)

Show the spec location (the tracker reference or `<run_dir>/spec.md`) and a three-line summary. The spec must already pass `python3 -m kinetic.spec_lint <file>` (exit 0). Ask: "Approve this spec?" Options: approve, revise.

## Breakdown gate (after tickets; records the grant)

Before asking, `python3 -m kinetic.graph validate --run <run_dir>` must print empty `errors`. Show the ticket list, human tickets first with their one-line reason: id, type, repo (human tickets may have none), blocked-by with edge types, after / ships-with / related where set, and interfaces (produces / consumes, agent tickets only). Show every `warnings` entry under the list (an interface no ticket produces) so the user can confirm it already exists.

The question must spell out the grant in substance:

> Approving this breakdown grants the build agents, for the tickets and repos listed, to: commit and push to the ticket branch, move ticket status in the tracker, and open draft PRs. It never grants: pushes to master or Release branches, force-push after review, deploys without the deploy hook's confirmation, or prod data writes.

Options: approve (record the grant), revise tickets. In the quick lane this is the same question with the single ticket; also ask which seams its tests may use, and put the answer in the ticket file. The run's Grant line given to each implementer is the approved wording shortened to: `Grant: commit and push to ticket branch; tracker status moves; draft PRs; never master/Release, force-push after review, deploys, prod data writes`. Do not extend it.

## Ship gate (before the ship skill)

Show per repo: integration branch, base branch, merge order (`python3 -m kinetic.gitops merge-order --run <run_dir>`), and the latest verify result per repo from state. Ask: "Push the integration branches and open draft PRs?" Options: approve, hold.

On approve, record the gate then read and follow `skills/ship/SKILL.md`. Push and PR creation, Atlassian MCP writes and Bash commands such as `gh` are additionally confirmed by hooks (other MCP tracker writes, for example Linear, are covered only by the grant); a hook denial is final: report it to the user, do not retry another way. Deploy is a separate hook-confirmed step and is never covered by any gate.

The run counts as shipped when `gates["ship"]["approved"]` true and phase `ship`; retro follows.
