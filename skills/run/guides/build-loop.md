# Build loop and review phase

You stay thin: never read code or full diffs. Read only script JSON, the first lines of reports, and reviewer replies.

## Setup (once, before round 1)

1. Validate: `python3 -m kinetic.graph validate --run <run_dir>`. Stop on any `errors` and send the user back to the tickets phase. This must come first: `frontier` returns an empty list on a cycle, which would look like "nothing to do".
2. The breakdown gate must be recorded approved (`gates.md`).
3. For each repo in play, find its base branch (`base_branch` in repo config, default `main`) and register it with the worktree as its path and integration branch `kinetic/<run-id>`:
   - Create the worktree with the `checkout-ticket-repos` skill if available (branch `kinetic/<run-id>` off the base). If it is not available: `python3 -m kinetic.gitops worktree --repo <repo-path> --dest <workspace>/<run-id>/worktrees/<repo> --branch kinetic/<run-id> --base <base>`.
   - `python3 -m kinetic.state set-repo --run <run_dir> --name <repo> --path <worktree> --integration-branch kinetic/<run-id>`
4. Make `<run_dir>/reports` and `<run_dir>/reviews` exist. Ticket branches are created per ticket from the repo's integration branch: `python3 -m kinetic.gitops worktree --repo <repo-worktree> --dest <run_dir>/worktrees/<repo>-<id> --branch kinetic/<run-id>/<id> --base kinetic/<run-id>` and the ticket's worktree is where its implementer works; record it with `set-ticket --id <id> --field branch=kinetic/<run-id>/<id>` and `set-ticket --id <id> --field worktree=<run_dir>/worktrees/<repo>-<id>`.

## Each round

1. `python3 -m kinetic.frontier --run <run_dir>` prints `{"ready": [ids]}`. It already applies the cap of 3 and one running per repo; do not second-guess it. Empty and every ticket merged/done: leave the loop. Empty with tickets still running, needs_decision or blocked: wait for returns.
2. Dispatch every ready ticket in ONE message: one `implementer` agent call per id, each with `run_in_background: true`. Each brief is exactly these lines:

```
Run: <run_dir>
Ticket: <id>
Repo: <ticket worktree>
Repo name: <repo>
Ticket file: <run_dir>/issues/<id>.md   (or, in jira mode: Jira key: <id>)
Report: <run_dir>/reports/<id>.md
Grant: <the Grant line from gates.md>
```

3. For each dispatched id: `python3 -m kinetic.state set-ticket --run <run_dir> --id <id> --field status=running`.

## On each implementer return

Read only the first lines of `<run_dir>/reports/<id>.md` (the `Status:` line, then Branch, Verify, Questions, Concerns).

**DONE or DONE_WITH_CONCERNS**

1. Set the ticket `done` or `done_with_concerns`.
2. Dispatch `standards-reviewer` and `spec-reviewer` in one message with the briefs their agent files define: `Run`, `Ticket`, `Repo` (the ticket worktree), `Diff: kinetic/<run-id>...kinetic/<run-id>/<id>` and `Output file: <run_dir>/reviews/<id>-<axis>.md`. Save each reply to `<run_dir>/reviews/<id>-standards.md` and `<run_dir>/reviews/<id>-spec.md` (the reviewers return text; you write the file).
3. Weigh the findings with `superpowers:receiving-code-review` if available (otherwise judge each finding against the ticket's acceptance criteria and verify it before acting). Do not act on a finding you cannot confirm.
4. If a fix is needed, dispatch a fix `implementer` for the same ticket (same brief; Report path `<run_dir>/reports/<id>-fix-N.md`; add a `Fix:` line listing the confirmed findings, each by id and one sentence). Its return goes through this section again. Allow at most 3 fix rounds per ticket, then ask the user.
5. Merge: `python3 -m kinetic.gitops merge --repo <the repo's integration worktree, its path in state> --ticket-branch kinetic/<run-id>/<id> --integration-branch kinetic/<run-id>`. Exit 0 and `merged: true`: set the ticket `merged`. On conflicts, follow `resolving-merge-conflicts` if available; if not, stop and ask the user. Never resolve by discarding the ticket's work.
6. Pin downstream: for every repo that has a ticket with a `snapshot` edge on this ticket's repo, run `python3 -m kinetic.gitops pin --run <run_dir> --upstream <upstream repo> --downstream <downstream repo>`. Exit 0 marks the upstream tickets `snapshot_published`; on failure show `log_path` to the user and ask. Do this only when the whole upstream repo state needed by the edge is merged.
Leave the ticket worktree in place for recovery.

**NEEDS_DECISION or BLOCKED**

Set the status (`needs_decision` or `blocked`). Ask the user with AskUserQuestion, quoting the report's `Questions:` (or the block reason and verify log path). Record the answer: `python3 -m kinetic.state add-ruling --run <run_dir> --what "<question>" --why "<answer and reasoning>" --cost "<effect on scope or time>"`. Resume the same implementer with SendMessage carrying the answer; set the ticket back to `running`. The ticket keeps occupying its repo while it waits, so no other ticket in that repo starts.

Then start the next round. Loop until the frontier is empty and every ticket is `merged` or `released`.

## Review phase

`set-phase review`. For each repo's integration worktree, with its base branch:

- `dev-fleet:architecture-review <worktree> <base>` if available.
- `/security-review` on the integration branch if available.

Say which of the two ran and which were unavailable. Apply confirmed findings by fix implementers through the same loop (new ticket status todo is not needed: dispatch the fix implementer directly, merge it into the integration branch). At most 3 rounds of fixes, then take the open findings to the user. Re-run verify on every changed repo before moving on: `python3 -m kinetic.verify --run <run_dir> --repo-name <repo> --repo-path <worktree>`; non-zero exit blocks the ship gate.
