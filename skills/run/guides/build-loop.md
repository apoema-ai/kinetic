# Build loop and review phase

You stay thin: never read code or full diffs. Read only script JSON, the first lines of reports, and reviewer replies.

## Setup (once, before round 1)

1. Validate: `kinetic graph validate --run <run_dir>`. Stop on any `errors` and send the user back to the tickets phase. This must come first: `frontier` returns an empty list on a cycle, which would look like "nothing to do".
2. The breakdown gate must be recorded approved (`gates.md`).
3. Repos and integration worktrees already exist: the discover phase registered every repo in `state.repos` with its worktree `<run_dir>/worktrees/<repo>` on `kinetic/<run-id>/integration`. Check them:
   - Every agent ticket's repo must be in `state.repos` (`graph validate` in step 1 reports it). A run started before the discover phase existed has empty `state.repos`: run `skills/discover/SKILL.md` with `Mode: confirm-only` on its tickets' repos first. Any other missing repo means a ticket was added after the breakdown gate: stop, `set-phase tickets`, and ask the breakdown gate again, so the grant names every repo.
   - A repo in state whose worktree directory is gone (recovery): recreate it with `kinetic gitops worktree --repo <repo-path from repos.json> --dest <run_dir>/worktrees/<repo> --branch kinetic/<run-id>/integration --base <base>` (base: `base_branch` in repo config, default `main`). The integration branch is never just `kinetic/<run-id>`: git cannot hold both that and `kinetic/<run-id>/<id>`.
4. Make `<run_dir>/reports`, `<run_dir>/reviews` and `<run_dir>/issues` exist. Ticket worktrees are NOT created here: each is cut at dispatch time (round step 2) so it starts from the integration branch as it is then, after its upstream tickets merged.

## Each round

1. Local mode only: first run `kinetic board drift --run <run_dir>`. If `drift` is non-empty, show each difference (id, key, file value, state value) and ask: apply the file's value to state through `set-ticket` / `human-done`, or overwrite the file with `kinetic board header --run <run_dir> --id <id>`. After every state change in this loop run `board header` for that ticket and then `board render`.
2. `kinetic frontier --run <run_dir>` prints `{"ready": [...], "waiting_on_you": [...], "only_human_left": bool}`. It already applies the cap of 3 and one running per repo; do not second-guess it. Never dispatch a human ticket. When `waiting_on_you` is non-empty, print it every round: for each id its checklist (the manual steps from its ticket), the tickets blocked behind it, and its tracker link (the adapter's "ticket reference" for its `tracker_ref` when present, otherwise its id; the file path in local mode). Empty cases:
   - Every agent ticket `merged` or `released`: leave the loop, even when human tickets are still open. Open human tickets are carried into review and ship as open items (they appear in Manual steps; ship's merge blocker applies only to human tickets a repo's tickets are blocked by). Checked first, before the `only_human_left` case.
   - Tickets still `running`, `needs_decision` or `blocked`: wait for returns.
   - `only_human_left` is true while agent tickets remain un-merged (nothing agent-side can move and a human can act now on the tickets in `waiting_on_you`): stop with "Only human tickets are left: <list>. Tell me when one is done, or say `ship` to continue with them open (the agent tickets behind them then ship as not merged, flagged as merge blockers)." This is its own case, checked before the stalled case below. It does not claim nothing else is stalled.
   - Otherwise, tickets remain `todo` and nothing is occupying a repo: the loop is stalled on edges that will never clear by themselves. Show the user each waiting ticket with the unsatisfied edge and why (a `snapshot` edge whose upstream repo has no `publish_snapshot` and `pin` configured, a `release` edge nobody has marked released, a blocker that is `blocked`). Ask whether to change the edge type (update the ticket with `set-ticket --field 'blocked_by=[...]'` and the tracker), mark a release by hand, or stop. Never dispatch around an edge.
   - A `release` edge is satisfied only by a manual step: once the upstream version is actually released, run `kinetic state set-ticket --run <run_dir> --id <upstream-id> --field status=released`.
   - **"Done with <id>"** from the user (with an optional note or link): run `kinetic state human-done --run <run_dir> --id <id> [--note <text>]` (plain `set-ticket --field status=done` on a human ticket is refused), mirror it through the adapter (on the ticket's `tracker_ref` when present, otherwise its id: "move status" to `names.status.done`, plus "comment" when there is a note), then run `board header` and `board render` in local mode and re-run the frontier.
3. For each ready id, prepare it (all of this before any dispatch):
   - Ticket file: in local mode the tickets skill already wrote `<run_dir>/issues/<id>.md`. For a quick-lane or `--from build` ticket, write `<run_dir>/issues/<id>.md` yourself from the ref (copy the ticket file if the ref is one; otherwise write the title and acceptance criteria from the ref's text or the issue fetched through the adapter) before dispatch.
   - Worktree: `kinetic gitops worktree --repo <repo's integration worktree> --dest <run_dir>/worktrees/<repo>-<id> --branch kinetic/<run-id>/<id> --base kinetic/<run-id>/integration`, then `set-ticket --id <id> --field branch=kinetic/<run-id>/<id>` and `set-ticket --id <id> --field worktree=<run_dir>/worktrees/<repo>-<id>`. If the worktree already exists (recovery), keep it.
   - Mark it running first, so a crash cannot leave a live worktree marked `todo`: `kinetic state set-ticket --run <run_dir> --id <id> --field status=running`.
4. Start every prepared ticket in parallel, each `implementer` in the background: one dispatch per id, all at once. Each brief is exactly these lines:

```
Run: <run_dir>
Docs: <run_dir>/docs
Ticket: <id>
Repo: <ticket worktree>
Repo name: <repo>
Ticket ref: <id>
Tracker adapter: <adapter path from `kinetic tracker resolve`>
Ticket file: <run_dir>/issues/<id>.md   (local mode only)
Report: <run_dir>/reports/<id>.md
Grant: <the Grant line from gates.md>
```

`Tracker adapter:` is the literal path the `adapter` key of `kinetic tracker resolve` gives. Agents run `kinetic <module>` commands like you do; `kinetic` is on their PATH. `Docs:` holds the glossary and ADR drafts the grill phase wrote (it may not exist).

## Resume or fresh implementer

`kinetic harness` (run preflight) reports `Resume sub-agent: yes|no` for the active harness. Whenever a running implementer needs more input — a `Fix:` file, an answer to its `Questions:`, a ruling — pick the path from that line:

- **yes**: resume the same implementer with the input; it keeps its context.
- **no, or the resume fails**: start a fresh `implementer` on the same worktree (same branch, same `Repo:`) with the normal brief plus `Previous report: <run_dir>/reports/<id>.md` and the input on its own line — `Fix: <findings file>`, `Answer: <the supplied context>`, or `Ruling: <n>` where `<n>` is the ruling's 1-based position in the run's `rulings` list in state.json (`add-ruling` prints the whole list; the new entry is last). On fix round 3 the fresh dispatch is `implementer-strong` instead.

Both paths rely only on saved state — the report file, the worktree, the rulings — never on a live agent's context, so a harness that cannot resume and an agent that died take the same fresh path; `recovery.md` uses it too.

## On each implementer return

Read only the first lines of `<run_dir>/reports/<id>.md` (the `Status:` line, then Branch, Verify, Questions, Concerns).

**DONE or DONE_WITH_CONCERNS**

1. Set the ticket `done` or `done_with_concerns` with `set-ticket --field status=done` (or `done_with_concerns`). The CLI refuses unless the ticket has a passing verify newer than its last edit. A report is a claim; the verify record is the evidence. On a refusal, treat the return as BLOCKED: show the refusal to the user, then either resume the implementer to re-run verify or keep the ticket `running`.
2. Note the ticket branch head (`git -C <ticket worktree> rev-parse HEAD`) as the review base for any fix round. Dispatch `standards-reviewer` and `spec-reviewer` in parallel with the briefs their agent files define: `Run`, `Ticket`, `Repo` (the ticket worktree), `Diff: kinetic/<run-id>/integration...kinetic/<run-id>/<id>`, `Ticket ref: <id>`, `Tracker adapter: <path>`, `Ticket file: <run_dir>/issues/<id>.md` (local mode only) and `Output file: <run_dir>/reviews/<id>-<axis>.md`. Save each reply to `<run_dir>/reviews/<id>-standards.md` and `<run_dir>/reviews/<id>-spec.md` (the reviewers return text; you write the file). Apply the reviewer read-only check below to the ticket worktree for this dispatch.
3. Weigh the findings with `superpowers:receiving-code-review` if available (otherwise judge each finding against the ticket's acceptance criteria and verify it before acting). Do not act on a finding you cannot confirm. Minor findings never enter the fix loop, but never drop them: append each confirmed Minor, one per line as `<id> minor: <file:line> <issue>`, to `<run_dir>/reviews/out-of-scope.md` so the integration review sees it (it is the same file the fix rounds feed). Both verdicts Approved, or no confirmed Critical or Important finding: go to step 5.
4. **Fix rounds**, at most 3 per ticket. Before each round set the ticket back to `running` (`set-ticket --field status=running`; this keeps its repo occupied and keeps the Stop gate off it) and write the confirmed findings for round N, one per line with an id (`F1`, `F2`, ...), to `<run_dir>/reviews/<id>-findings-N.md`.
   - **Rounds 1 and 2**: send `Fix: <run_dir>/reviews/<id>-findings-N.md` to the implementer — resume it where the harness can, else the fresh-implementer path above. It fixes only those findings, re-verifies and appends a `## Fix round N` section to its report.
   - **Round 3**: dispatch a fresh `implementer-strong` with the normal brief plus the `Fix:` line. A stronger model with fresh eyes, since two rounds on the first one did not converge. Rounds 1 and 2 already take the fresh path when the harness cannot resume or the resume fails (see above).
   - After each round, dispatch `fix-reviewer` (brief in its agent file; `Fix diff: <review base>..<new head>`; `Output file: <run_dir>/reviews/<id>-fix-N.md`) instead of the two full reviewers, and save its reply. Run the same reviewer read-only check on the ticket worktree around this dispatch. Its Out of scope items do not extend the loop: append them to `<run_dir>/reviews/out-of-scope.md` for the integration review. `Verdict: Approved`: set the ticket `done` again as in step 1, then go to step 5. Otherwise the review base becomes the new head and the open findings go to the next round.
   - **After round 3, adjudicate** each finding still open. One that blocks an acceptance criterion, the threat model or a contract other repos rely on goes to the user (ask with the harness's question tool when the profile names one, chat otherwise: fix it yourself, accept it, or stop). Any other is recorded as a ruling (`add-ruling --what "<finding>" --why "<why it does not block>" --cost "<what it costs if wrong>"`) and the ticket proceeds.
   - After a crash during a fix round, recovery cannot tell a dead fix agent from a finished first round (`reports/<id>.md` already exists): check the report's latest `## Fix round` section and `reviews/<id>-fix-N.md` by hand.
5. Merge: `kinetic gitops merge --repo <the repo's integration worktree, its path in state> --ticket-branch kinetic/<run-id>/<id> --integration-branch kinetic/<run-id>/integration`. Exit 0 and `merged: true`: set the ticket `merged`. On conflicts, follow `resolving-merge-conflicts` if available; if not, stop and ask the user. Never resolve by discarding the ticket's work.
6. Pin downstream: for every repo that has a ticket with a `snapshot` edge on this ticket's repo, run `kinetic gitops pin --run <run_dir> --upstream <upstream repo> --downstream <downstream repo>`. Exit 0 marks the upstream tickets `snapshot_published`; on failure show the result's `reason` (or `log_path` when set) to the user and ask. Do this only when the whole upstream repo state needed by the edge is merged.
Leave the ticket worktree in place for recovery.

**NEEDS_HUMAN**

The report's `Manual step:` section names a step only a person can do. Then:

1. Create a human ticket `<id>-human-N` (N from 1, next unused for that original) with the report's manual step as its checklist and its expected outcome: `kinetic state set-ticket --run <run_dir> --id <id>-human-N --field kind=human --field 'blocked_by=[]'` (no repo), creating the tracker issue through the adapter ("create child" under the original ticket's slice parent, "set kind" with `names.kind.human`, "assign to user") and, in local mode, writing `<run_dir>/issues/<id>-human-N.md` then `board header`. On a remote tracker, store the key "create child" returned: `kinetic state set-ticket --run <run_dir> --id <id>-human-N --field tracker_ref=<key>`. Everywhere you link, move status, comment on or show a tracker link for a ticket, use its `tracker_ref` when present, otherwise its id.
2. Append `{"id": "<id>-human-N", "type": "merge"}` to the original ticket's `blocked_by` (`set-ticket --field 'blocked_by=[...]'` with the existing entries kept) and link it through the adapter ("link blocker", using each ticket's `tracker_ref` when present). An edge onto a human blocker is satisfied when it is done.
3. Rename the original's report to `<run_dir>/reports/<id>.needs-human-N.md` (N as above) so crash recovery does not replay it as a fresh return. Then set the original back to `todo` (`set-ticket --field status=todo`), keeping its worktree and branch; the next dispatch reuses them. Mirror it through the adapter: "move status" to `names.status.todo`.
4. Show the new ticket to the user (checklist, why it is needed, link). Run `board render` in local mode. The next frontier lists it under `waiting_on_you`.

**NEEDS_CONTEXT**

The implementer is missing information you can supply. Keep the ticket `running`. Answer from what you can read without reading code yourself (state, config, the spec, the ticket, ADRs, a script's JSON); send the answer to the implementer — resume it with `Answer: <the answer>` where the harness can, else the fresh-implementer path above. Ask the user only if you cannot answer; then handle it as NEEDS_DECISION.

**NEEDS_DECISION or BLOCKED**

Set the status (`needs_decision` or `blocked`). Ask the user — the harness's question tool when the profile names one, chat otherwise — quoting the report's `Questions:` (or the block reason and verify log path). Record the answer: `kinetic state add-ruling --run <run_dir> --what "<question>" --why "<answer and reasoning>" --cost "<effect on scope or time>"`. Then send the ruling to the implementer: resume the same one with `Ruling: <n>` where the harness can, else the fresh-implementer path above; set the ticket back to `running`. The ticket keeps occupying its repo while it waits, so no other ticket in that repo starts.

Then start the next round. Loop until every agent ticket is `merged` or `released`. Human tickets still open then do not hold the loop; they go forward as open items.

## Review phase

`set-phase review`. Always dispatch one `integration-reviewer` for the whole run (brief in its agent file: `Run`, `Spec`, `Tracker adapter: <adapter path from resolve>`, one `Repo:` line per repo with its integration worktree and `<base>..kinetic/<run-id>/integration`, `Merge order` from `kinetic.gitops merge-order`, `Output file: <run_dir>/reviews/integration.md`). Record each worktree named in its brief and run the reviewer read-only check on them around the dispatch. Save its reply, and weigh its findings together with `<run_dir>/reviews/out-of-scope.md` if it exists (deferred Minor findings from the ticket reviews and out-of-scope items from fix rounds); triage each of its lines, so one that matters before merge becomes a confirmed finding and the rest are stated as deferred in the ship report. In addition, for each repo's integration worktree, with its base branch:

- `dev-fleet:architecture-review <worktree> <base>` if available.
- `/security-review` on the integration branch if available.

Say which of the two optional ones ran and which were unavailable. Apply confirmed findings through fix tickets, one per repo and fix round, named `<repo>-review-N` (N from 1 per repo): write `<run_dir>/issues/<repo>-review-N.md` with the confirmed findings as `- [ ]` acceptance criteria, then `kinetic state set-ticket --run <run_dir> --id <repo>-review-N --field repo=<repo> --field 'blocked_by=[]'`. Run the normal build rounds above for it: it gets its own worktree, issues file and report (`<run_dir>/reports/<repo>-review-N.md`), goes through the reviewers, and merges into the integration branch. At most 3 fix rounds per repo, then take the open findings to the user. Re-run verify on every changed repo before moving on: `kinetic verify --run <run_dir> --repo-name <repo> --repo-path <worktree>`; non-zero exit blocks the ship gate.

## Reviewer read-only check

A reviewer must never change the worktree it reviews, on any harness. Where the harness can restrict the reviewer's tools, keep that allow-list; this check is the backstop everywhere.

Before dispatching a reviewer, for each worktree named in its brief (`Repo:` lines), record:

- head: `git -C <worktree> rev-parse HEAD`
- clean tree: `git -C <worktree> status --porcelain` must print nothing; if it does not, commit the work or stop and ask the user — never run the restore below over uncommitted work you did not record
- status hash: `kinetic gitops status-hash --repo <worktree>` — keep the `status_hash` value from its JSON output

After the reviewer returns and before you read or save its reply, run:

`kinetic gitops assert-unchanged --repo <worktree> --head <sha> --status-hash <h>`

Exit 0 means the worktree is untouched and the review counts. Non-zero means the reviewer changed it: restore the worktree to the recorded state — `git -C <worktree> reset --hard <sha>` then `git -C <worktree> clean -fd` (safe only because you recorded a clean tree before the review, so this discards only what the reviewer left) — discard the review (do not save its reply to the output file) and dispatch the reviewer again once with the same brief and the same recorded values. If the check fails a second time, stop and ask the user. Never act on a review whose check failed.
