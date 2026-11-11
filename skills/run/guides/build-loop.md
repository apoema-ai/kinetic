# Build loop and review phase

You stay thin: never read code or full diffs. Read only script JSON, the first lines of reports, and reviewer replies.

## Setup (once, before round 1)

1. Validate: `python3 -m kinetic.graph validate --run <run_dir>`. Stop on any `errors` and send the user back to the tickets phase. This must come first: `frontier` returns an empty list on a cycle, which would look like "nothing to do".
2. The breakdown gate must be recorded approved (`gates.md`).
3. For each repo in play, find its base branch (`base_branch` in repo config, default `main`) and register it with the worktree as its path and integration branch `kinetic/<run-id>/integration` (git cannot hold both `kinetic/<run-id>` and `kinetic/<run-id>/<id>`, so the integration branch is never just `kinetic/<run-id>`):
   - Create the worktree with the `checkout-ticket-repos` skill if available (branch `kinetic/<run-id>/integration` off the base). If it is not available: `python3 -m kinetic.gitops worktree --repo <repo-path> --dest <run_dir>/worktrees/<repo> --branch kinetic/<run-id>/integration --base <base>`.
   - `python3 -m kinetic.state set-repo --run <run_dir> --name <repo> --path <worktree> --integration-branch kinetic/<run-id>/integration`
4. Make `<run_dir>/reports`, `<run_dir>/reviews` and `<run_dir>/issues` exist. Ticket worktrees are NOT created here: each is cut at dispatch time (round step 2) so it starts from the integration branch as it is then, after its upstream tickets merged.

## Each round

1. `python3 -m kinetic.frontier --run <run_dir>` prints `{"ready": [ids]}`. It already applies the cap of 3 and one running per repo; do not second-guess it. Three empty cases:
   - Every ticket `merged` or `released`: leave the loop.
   - Tickets still `running`, `needs_decision` or `blocked`: wait for returns.
   - Tickets remain `todo` and nothing is occupying a repo: the loop is stalled on edges that will never clear by themselves. Show the user each waiting ticket with the unsatisfied edge and why (a `snapshot` edge whose upstream repo has no `publish_snapshot` and `pin` configured, a `release` edge nobody has marked released, a blocker that is `blocked`). Ask whether to change the edge type (update the ticket with `set-ticket --field 'blocked_by=[...]'` and the tracker), mark a release by hand, or stop. Never dispatch around an edge.
   - A `release` edge is satisfied only by a manual step: once the upstream version is actually released, run `python3 -m kinetic.state set-ticket --run <run_dir> --id <upstream-id> --field status=released`.
2. For each ready id, prepare it (all of this before any dispatch):
   - Ticket file: in local mode the tickets skill already wrote `<run_dir>/issues/<id>.md`. For a quick-lane or `--from build` ticket, write `<run_dir>/issues/<id>.md` yourself from the ref (copy the ticket file if the ref is one; otherwise write the title and acceptance criteria from the ref's text or the Jira issue) before dispatch.
   - Worktree: `python3 -m kinetic.gitops worktree --repo <repo's integration worktree> --dest <run_dir>/worktrees/<repo>-<id> --branch kinetic/<run-id>/<id> --base kinetic/<run-id>/integration`, then `set-ticket --id <id> --field branch=kinetic/<run-id>/<id>` and `set-ticket --id <id> --field worktree=<run_dir>/worktrees/<repo>-<id>`. If the worktree already exists (recovery), keep it.
   - Mark it running first, so a crash cannot leave a live worktree marked `todo`: `python3 -m kinetic.state set-ticket --run <run_dir> --id <id> --field status=running`.
3. Dispatch every prepared ticket in ONE message: one `implementer` agent call per id, each with `run_in_background: true`. Each brief is exactly these lines:

```
Run: <run_dir>
Scripts: <plugin-root>/scripts
Docs: <run_dir>/docs
Ticket: <id>
Repo: <ticket worktree>
Repo name: <repo>
Ticket file: <run_dir>/issues/<id>.md   (or, in jira mode: Jira key: <id>)
Report: <run_dir>/reports/<id>.md
Grant: <the Grant line from gates.md>
```

`<plugin-root>` is the absolute path to the kinetic plugin (see `run/SKILL.md`); agents get no expansion of `${CLAUDE_PLUGIN_ROOT}`, so always pass the literal path. `Docs:` holds the glossary and ADR drafts the grill phase wrote (it may not exist).

## On each implementer return

Read only the first lines of `<run_dir>/reports/<id>.md` (the `Status:` line, then Branch, Verify, Questions, Concerns).

**DONE or DONE_WITH_CONCERNS**

1. Set the ticket `done` or `done_with_concerns`.
2. Dispatch `standards-reviewer` and `spec-reviewer` in one message with the briefs their agent files define: `Run`, `Ticket`, `Repo` (the ticket worktree), `Diff: kinetic/<run-id>/integration...kinetic/<run-id>/<id>`, `Ticket file: <run_dir>/issues/<id>.md` (or, in jira mode, `Jira key: <id>`) and `Output file: <run_dir>/reviews/<id>-<axis>.md`. Save each reply to `<run_dir>/reviews/<id>-standards.md` and `<run_dir>/reviews/<id>-spec.md` (the reviewers return text; you write the file).
3. Weigh the findings with `superpowers:receiving-code-review` if available (otherwise judge each finding against the ticket's acceptance criteria and verify it before acting). Do not act on a finding you cannot confirm.
4. If a fix is needed, set the ticket back to `running` (`set-ticket --field status=running`; this keeps its repo occupied and keeps the Stop gate off it; recovery cannot yet tell a dead fix agent from a finished first round, because `reports/<id>.md` already exists, so after a crash during a fix round re-check `reports/<id>-fix-N.md` by hand), then dispatch a fix `implementer` for the same ticket (same brief; Report path `<run_dir>/reports/<id>-fix-N.md`; add a `Fix:` line listing the confirmed findings, each by id and one sentence). Its return goes through this section again and sets the ticket `done` or `done_with_concerns` as in step 1. Allow at most 3 fix rounds per ticket, then ask the user.
5. Merge: `python3 -m kinetic.gitops merge --repo <the repo's integration worktree, its path in state> --ticket-branch kinetic/<run-id>/<id> --integration-branch kinetic/<run-id>/integration`. Exit 0 and `merged: true`: set the ticket `merged`. On conflicts, follow `resolving-merge-conflicts` if available; if not, stop and ask the user. Never resolve by discarding the ticket's work.
6. Pin downstream: for every repo that has a ticket with a `snapshot` edge on this ticket's repo, run `python3 -m kinetic.gitops pin --run <run_dir> --upstream <upstream repo> --downstream <downstream repo>`. Exit 0 marks the upstream tickets `snapshot_published`; on failure show the result's `reason` (or `log_path` when set) to the user and ask. Do this only when the whole upstream repo state needed by the edge is merged.
Leave the ticket worktree in place for recovery.

**NEEDS_DECISION or BLOCKED**

Set the status (`needs_decision` or `blocked`). Ask the user with AskUserQuestion, quoting the report's `Questions:` (or the block reason and verify log path). Record the answer: `python3 -m kinetic.state add-ruling --run <run_dir> --what "<question>" --why "<answer and reasoning>" --cost "<effect on scope or time>"`. Resume the same implementer with SendMessage carrying the answer; set the ticket back to `running`. The ticket keeps occupying its repo while it waits, so no other ticket in that repo starts.

Then start the next round. Loop until the frontier is empty and every ticket is `merged` or `released`.

## Review phase

`set-phase review`. For each repo's integration worktree, with its base branch:

- `dev-fleet:architecture-review <worktree> <base>` if available.
- `/security-review` on the integration branch if available.

Say which of the two ran and which were unavailable. Apply confirmed findings through fix tickets, one per repo and fix round, named `<repo>-review-N` (N from 1 per repo): write `<run_dir>/issues/<repo>-review-N.md` with the confirmed findings as `- [ ]` acceptance criteria, then `python3 -m kinetic.state set-ticket --run <run_dir> --id <repo>-review-N --field repo=<repo> --field 'blocked_by=[]'`. Run the normal build rounds above for it: it gets its own worktree, issues file and report (`<run_dir>/reports/<repo>-review-N.md`), goes through the reviewers, and merges into the integration branch. At most 3 fix rounds per repo, then take the open findings to the user. Re-run verify on every changed repo before moving on: `python3 -m kinetic.verify --run <run_dir> --repo-name <repo> --repo-path <worktree>`; non-zero exit blocks the ship gate.
