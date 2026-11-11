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

1. Local mode only: first run `python3 -m kinetic.board drift --run <run_dir>`. If `drift` is non-empty, show each difference (id, key, file value, state value) and ask: apply the file's value to state through `set-ticket` / `human-done`, or overwrite the file with `python3 -m kinetic.board header --run <run_dir> --id <id>`. After every state change in this loop run `board header` for that ticket and then `board render`.
2. `python3 -m kinetic.frontier --run <run_dir>` prints `{"ready": [...], "waiting_on_you": [...], "only_human_left": bool}`. It already applies the cap of 3 and one running per repo; do not second-guess it. Never dispatch a human ticket. When `waiting_on_you` is non-empty, print it every round: for each id its checklist (the manual steps from its ticket), the tickets blocked behind it, and its tracker link (the adapter's "ticket reference"; the file path in local mode). Empty cases:
   - Every ticket `merged` or `released`: leave the loop.
   - Tickets still `running`, `needs_decision` or `blocked`: wait for returns.
   - `only_human_left` is true (nothing agent-side can move and a human can act now on the tickets in `waiting_on_you`): stop with "Only human tickets are left: <list>. Tell me when one is done." This is its own case, checked before the stalled case below. It does not claim nothing else is stalled.
   - Otherwise, tickets remain `todo` and nothing is occupying a repo: the loop is stalled on edges that will never clear by themselves. Show the user each waiting ticket with the unsatisfied edge and why (a `snapshot` edge whose upstream repo has no `publish_snapshot` and `pin` configured, a `release` edge nobody has marked released, a blocker that is `blocked`). Ask whether to change the edge type (update the ticket with `set-ticket --field 'blocked_by=[...]'` and the tracker), mark a release by hand, or stop. Never dispatch around an edge.
   - A `release` edge is satisfied only by a manual step: once the upstream version is actually released, run `python3 -m kinetic.state set-ticket --run <run_dir> --id <upstream-id> --field status=released`.
   - **"Done with <id>"** from the user (with an optional note or link): run `python3 -m kinetic.state human-done --run <run_dir> --id <id> [--note <text>]` (plain `set-ticket --field status=done` on a human ticket is refused), mirror it through the adapter ("move status" to `names.status.done`, plus "comment" when there is a note), then run `board header` and `board render` in local mode and re-run the frontier.
3. For each ready id, prepare it (all of this before any dispatch):
   - Ticket file: in local mode the tickets skill already wrote `<run_dir>/issues/<id>.md`. For a quick-lane or `--from build` ticket, write `<run_dir>/issues/<id>.md` yourself from the ref (copy the ticket file if the ref is one; otherwise write the title and acceptance criteria from the ref's text or the issue fetched through the adapter) before dispatch.
   - Worktree: `python3 -m kinetic.gitops worktree --repo <repo's integration worktree> --dest <run_dir>/worktrees/<repo>-<id> --branch kinetic/<run-id>/<id> --base kinetic/<run-id>/integration`, then `set-ticket --id <id> --field branch=kinetic/<run-id>/<id>` and `set-ticket --id <id> --field worktree=<run_dir>/worktrees/<repo>-<id>`. If the worktree already exists (recovery), keep it.
   - Mark it running first, so a crash cannot leave a live worktree marked `todo`: `python3 -m kinetic.state set-ticket --run <run_dir> --id <id> --field status=running`.
4. Dispatch every prepared ticket in ONE message: one `implementer` agent call per id, each with `run_in_background: true`. Each brief is exactly these lines:

```
Run: <run_dir>
Scripts: <plugin-root>/scripts
Docs: <run_dir>/docs
Ticket: <id>
Repo: <ticket worktree>
Repo name: <repo>
Ticket ref: <id>
Tracker adapter: <adapter path from `python3 -m kinetic.tracker resolve`>
Ticket file: <run_dir>/issues/<id>.md   (local mode only)
Report: <run_dir>/reports/<id>.md
Grant: <the Grant line from gates.md>
```

`Tracker adapter:` is the literal path the `adapter` key of `python3 -m kinetic.tracker resolve` gives; agents cannot expand `${CLAUDE_PLUGIN_ROOT}`. `<plugin-root>` is the absolute path to the kinetic plugin (see `run/SKILL.md`); agents get no expansion of `${CLAUDE_PLUGIN_ROOT}`, so always pass the literal path. `Docs:` holds the glossary and ADR drafts the grill phase wrote (it may not exist).

## On each implementer return

Read only the first lines of `<run_dir>/reports/<id>.md` (the `Status:` line, then Branch, Verify, Questions, Concerns).

**DONE or DONE_WITH_CONCERNS**

1. Set the ticket `done` or `done_with_concerns` with `set-ticket --field status=done` (or `done_with_concerns`). The CLI refuses unless the ticket has a passing verify newer than its last edit. A report is a claim; the verify record is the evidence. On a refusal, treat the return as BLOCKED: show the refusal to the user, then either resume the implementer to re-run verify or keep the ticket `running`.
2. Note the ticket branch head (`git -C <ticket worktree> rev-parse HEAD`) as the review base for any fix round. Dispatch `standards-reviewer` and `spec-reviewer` in one message with the briefs their agent files define: `Run`, `Ticket`, `Repo` (the ticket worktree), `Diff: kinetic/<run-id>/integration...kinetic/<run-id>/<id>`, `Ticket ref: <id>`, `Tracker adapter: <path>`, `Ticket file: <run_dir>/issues/<id>.md` (local mode only) and `Output file: <run_dir>/reviews/<id>-<axis>.md`. Save each reply to `<run_dir>/reviews/<id>-standards.md` and `<run_dir>/reviews/<id>-spec.md` (the reviewers return text; you write the file).
3. Weigh the findings with `superpowers:receiving-code-review` if available (otherwise judge each finding against the ticket's acceptance criteria and verify it before acting). Do not act on a finding you cannot confirm. Both verdicts Approved, or no confirmed Critical or Important finding: go to step 5.
4. **Fix rounds**, at most 3 per ticket. Before each round set the ticket back to `running` (`set-ticket --field status=running`; this keeps its repo occupied and keeps the Stop gate off it) and write the confirmed findings for round N, one per line with an id (`F1`, `F2`, ...), to `<run_dir>/reviews/<id>-findings-N.md`.
   - **Rounds 1 and 2**: resume the same implementer with SendMessage: `Fix: <run_dir>/reviews/<id>-findings-N.md`. It keeps its context, fixes only those findings, re-verifies and appends a `## Fix round N` section to its report.
   - **Round 3**: dispatch a fresh `implementer` with `model: "opus"` and the normal brief plus the `Fix:` line. A stronger model with fresh eyes, since two rounds on the first one did not converge. If the first implementer cannot be resumed (a new session), round 1 or 2 uses a fresh sonnet implementer the same way.
   - After each round, dispatch `fix-reviewer` (brief in its agent file; `Fix diff: <review base>..<new head>`; `Output file: <run_dir>/reviews/<id>-fix-N.md`) instead of the two full reviewers, and save its reply. Its Out of scope items do not extend the loop: append them to `<run_dir>/reviews/out-of-scope.md` for the integration review. `Verdict: Approved`: set the ticket `done` again as in step 1, then go to step 5. Otherwise the review base becomes the new head and the open findings go to the next round.
   - **After round 3, adjudicate** each finding still open. One that blocks an acceptance criterion, the threat model or a contract other repos rely on goes to the user (AskUserQuestion: fix it yourself, accept it, or stop). Any other is recorded as a ruling (`add-ruling --what "<finding>" --why "<why it does not block>" --cost "<what it costs if wrong>"`) and the ticket proceeds.
   - After a crash during a fix round, recovery cannot tell a dead fix agent from a finished first round (`reports/<id>.md` already exists): check the report's latest `## Fix round` section and `reviews/<id>-fix-N.md` by hand.
5. Merge: `python3 -m kinetic.gitops merge --repo <the repo's integration worktree, its path in state> --ticket-branch kinetic/<run-id>/<id> --integration-branch kinetic/<run-id>/integration`. Exit 0 and `merged: true`: set the ticket `merged`. On conflicts, follow `resolving-merge-conflicts` if available; if not, stop and ask the user. Never resolve by discarding the ticket's work.
6. Pin downstream: for every repo that has a ticket with a `snapshot` edge on this ticket's repo, run `python3 -m kinetic.gitops pin --run <run_dir> --upstream <upstream repo> --downstream <downstream repo>`. Exit 0 marks the upstream tickets `snapshot_published`; on failure show the result's `reason` (or `log_path` when set) to the user and ask. Do this only when the whole upstream repo state needed by the edge is merged.
Leave the ticket worktree in place for recovery.

**NEEDS_HUMAN**

The report's `Manual step:` section names a step only a person can do. Then:

1. Create a human ticket `<id>-human-N` (N from 1, next unused for that original) with the report's manual step as its checklist and its expected outcome: `python3 -m kinetic.state set-ticket --run <run_dir> --id <id>-human-N --field kind=human --field 'blocked_by=[]'` (no repo), creating the tracker issue through the adapter ("create child", "set kind" with `names.kind.human`, "assign to user") and, in local mode, writing `<run_dir>/issues/<id>-human-N.md` then `board header`.
2. Append `{"id": "<id>-human-N", "type": "merge"}` to the original ticket's `blocked_by` (`set-ticket --field 'blocked_by=[...]'` with the existing entries kept) and link it through the adapter ("link blocker"). An edge onto a human blocker is satisfied when it is done.
3. Set the original back to `todo` (`set-ticket --field status=todo`), keeping its worktree and branch; the next dispatch reuses them.
4. Show the new ticket to the user (checklist, why it is needed, link). Run `board render` in local mode. The next frontier lists it under `waiting_on_you`.

**NEEDS_CONTEXT**

The implementer is missing information you can supply. Keep the ticket `running`. Answer from what you can read without reading code yourself (state, config, the spec, the ticket, ADRs, a script's JSON); resume the same implementer with SendMessage carrying the answer. Ask the user only if you cannot answer; then handle it as NEEDS_DECISION.

**NEEDS_DECISION or BLOCKED**

Set the status (`needs_decision` or `blocked`). Ask the user with AskUserQuestion, quoting the report's `Questions:` (or the block reason and verify log path). Record the answer: `python3 -m kinetic.state add-ruling --run <run_dir> --what "<question>" --why "<answer and reasoning>" --cost "<effect on scope or time>"`. Resume the same implementer with SendMessage carrying the answer; set the ticket back to `running`. The ticket keeps occupying its repo while it waits, so no other ticket in that repo starts.

Then start the next round. Loop until the frontier is empty and every ticket is `merged` or `released`.

## Review phase

`set-phase review`. Always dispatch one `integration-reviewer` for the whole run (brief in its agent file: `Run`, `Spec`, one `Repo:` line per repo with its integration worktree and `<base>..kinetic/<run-id>/integration`, `Merge order` from `kinetic.gitops merge-order`, `Output file: <run_dir>/reviews/integration.md`). Save its reply, and weigh its findings together with `<run_dir>/reviews/out-of-scope.md` if it exists. In addition, for each repo's integration worktree, with its base branch:

- `dev-fleet:architecture-review <worktree> <base>` if available.
- `/security-review` on the integration branch if available.

Say which of the two optional ones ran and which were unavailable. Apply confirmed findings through fix tickets, one per repo and fix round, named `<repo>-review-N` (N from 1 per repo): write `<run_dir>/issues/<repo>-review-N.md` with the confirmed findings as `- [ ]` acceptance criteria, then `python3 -m kinetic.state set-ticket --run <run_dir> --id <repo>-review-N --field repo=<repo> --field 'blocked_by=[]'`. Run the normal build rounds above for it: it gets its own worktree, issues file and report (`<run_dir>/reports/<repo>-review-N.md`), goes through the reviewers, and merges into the integration branch. At most 3 fix rounds per repo, then take the open findings to the user. Re-run verify on every changed repo before moving on: `python3 -m kinetic.verify --run <run_dir> --repo-name <repo> --repo-path <worktree>`; non-zero exit blocks the ship gate.
