---
name: cleanup
description: Remove a kinetic run's local worktrees and branches whose work is merged. Uses the active run unless a run directory is given. Lists what would go and asks before removing anything; never touches unmerged work or the run directory.
model: sonnet
disable-model-invocation: true
triggers: [user]
argument-hint: "[run-dir]"
---

# Kinetic cleanup

Remove the local git worktrees and branches of one run once their work is merged. Run scripts as `kinetic <module> ...`.

## 1. Pick the run

The run directory is the argument if given, else the contents of `~/.config/kinetic/active-run`. Load it with `kinetic state load --run <run_dir>`. With no run, say so and stop.

The run id in branch names is the run directory's name: branches are `kinetic/<run-id>/integration` and `kinetic/<run-id>/<ticket-id>`.

## 2. Find what is merged (no changes yet)

For each repo in `state.repos` (its `path` is the integration worktree; its clone path is `path` in `~/.config/kinetic/repos.json`):

- **Ticket worktrees and branches.** For each ticket of this repo with a `worktree` or `branch` in state: it is removable when its branch is merged into the integration branch. Check with `git -C <integration worktree> branch --merged kinetic/<run-id>/integration --list 'kinetic/<run-id>/*'`.
- **The integration worktree and branch.** Removable only when the repo's PR is merged. Find the PR with `gh pr list --head kinetic/<run-id>/integration --state all --json number,state,headRefOid,url`, run from the clone path. Merged means `state` is `MERGED`. Note `headRefOid` for step 4.
  - No PR, or PR open or closed unmerged: keep the integration worktree and branch.
  - `gh` not available or not logged in: keep them, and say that the PR state could not be checked.

## 3. Ask once

Show one list, per repo: each worktree path and branch that would be removed, and each one kept with its reason (not merged, PR open, PR closed unmerged, PR state unknown). Ask the user to approve removal of the listed items, with the harness's question tool when the profile names one (`kinetic harness` prints it under `Question tool:`; `none` means chat). On no, stop and say the run can be cleaned up later with `/kinetic:cleanup <run_dir>`.

## 4. Remove

Only what the user approved, in this order:

1. Ticket worktrees: `git -C <integration worktree> worktree remove <ticket worktree>`. Then their branches, run from the integration worktree so git checks them against the integration branch: `git -C <integration worktree> branch -d kinetic/<run-id>/<ticket-id>`.
2. Integration worktree, for repos whose PR is merged: `git -C <clone path> worktree remove <integration worktree>`. Then `git -C <clone path> branch -d kinetic/<run-id>/integration`.
   - If `-d` refuses because the PR was squash- or rebase-merged, and the local branch tip (`git -C <clone path> rev-parse kinetic/<run-id>/integration`) equals the PR's `headRefOid`, everything on the branch is in the merged PR: delete it with `git -C <clone path> branch -D kinetic/<run-id>/integration`. If the tips differ, the branch has local commits the PR never had: keep it and report it.
3. `git -C <clone path> worktree prune`.

Never pass `--force` to `worktree remove`: a refusal means uncommitted changes. Never use `-D` except for the integration-branch case above. Report each refusal with its path and leave that item in place.

## 5. Report

List what was removed and what was kept, with the reason for each item kept. Never remove the run directory: it holds the state, reports, reviews and docs. Do not change `state.json`.

## 6. Offer to catalog

Only when `kinetic catalog show` exits 0 and step 2 found at least one repo whose PR is merged. Ask once, after the report: "Catalog this run's merged work?" The removals above never wait on this answer. On yes, follow `skills/catalog-refresh/SKILL.md` with `Run: <run_dir>`; it shows its own review and writes only what the user approves. On no, say it can be done later with `/kinetic:catalog-refresh --run <run_dir>`. Cleanup is the one skill that invokes another, and only this one.
