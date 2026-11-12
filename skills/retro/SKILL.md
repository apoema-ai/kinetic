---
name: retro
description: Retrospective on a kinetic run that suggests improvements to the agent environment and drafts a runbook and release notes. Use at the retro phase of a kinetic run.
model: sonnet
---

# Retro

Conduct a **retrospective** on the run. You are suggesting improvements to the coding agent's **environment** to improve future runs, and drafting the operational docs the run owes. This skill never invokes another skill.

The orchestrator passes `Run: <dir>` (the run directory, `<workspace>/<run-id>/`). Run scripts as `kinetic <module> ...`.

## Writing style for steering files

Anything you propose to put in a steering file (the repo's instruction file, see "Files" below), a skill or a standards file must be short, specific and actionable: navigation pointers rather than prose, one instruction per line, no instruction that wouldn't change the agent's behavior.

## Steps

1. Read the primary sources: `kinetic state load --run <dir>` (tickets, rulings, verify results, gates), `<run_dir>/reports/`, the spec, and the session logs on this machine if the user points at them. Default to the current session.

2. Look for candidates for improvement in these categories.

- **Navigation**: how easy was it to find the right files? Hidden dependencies between files? Would a **navigation pointer** help? _Use when_ finding a piece of information took a long time.
- **Automated checks**: could a linter, type check, test or filesystem check have caught a mistake the agent made? Read the repo's own check command first (its `lint`/`check` scripts, its CI workflow), so a check that already exists but sits unwired or silently broken is the finding, not a reinvention. A repo with no **guardrail** (no pre-commit hook and no CI job running lint/typecheck/test) is itself a finding. _Use when_ an automated check could have caught a mistake, or the repo has no guardrail at all.
- **Coding standards**: should the **reviewer agent** get a new rule, or an existing rule be removed or clarified? Classify the violation first: a **mechanical** one (fixed syntactic pattern, banned API, import shape, file-location rule) gets a deterministic check (custom lint rule, pre-commit hook or CI job); default to building the check over writing the rule. Reserve `CODING_STANDARDS.md` for genuine **judgement calls**. _Use when_ the reviewer failed to catch a mistake.
- **Global instruction file**: should steering instructions move to coding standards or automated checks? _Use when_ the file is large, in the repo or the user's global scope.
- **Tool economy**: expensive tool calls that could be streamlined; token-inefficient custom tooling.
- **No-ops**: steering instructions that don't change the agent's behavior. _Use when_ steering files are large.
- **Information access**: crucial information the agent lacked (dev server logs, read-only access to a third-party service).

3. Present the candidates to the user in order of severity.

4. Draft the run's operational docs under `<run_dir>/docs/` (create the directory):

- `<run_dir>/docs/runbook.md`: for operators of what shipped. Sections: what changed and where (repos, PRs), how to verify it is healthy, configuration and feature flags, rollout and rollback order (use `kinetic gitops merge-order --run <dir>`), known failure modes and what to do, who to ask.
- `<run_dir>/docs/release-notes.md`: for consumers. Group by slice; describe user-visible behavior in `<run_dir>/docs/GLOSSARY.md` language; call out breaking changes, migrations and required pins or version bumps.

Source facts from the spec, ticket reports and PRs, not from memory. Mark anything you could not verify as "unverified" instead of stating it as fact. These are drafts for the user to review.

5. Offer cleanup. Ticket worktrees and branches are kept until now for recovery. For each repo, check its PR state (`gh pr view <url> --json state --jq .state`, from the repo path):

- **PR merged:** offer to remove that repo's ticket worktrees and branches, and its integration worktree. List exactly what would go (`git -C <integration worktree> worktree list`, the `kinetic/<run-id>/*` branches), and ask before removing anything. Remove with `git -C <repo path> worktree remove <path>` and `git -C <repo path> branch -d <branch>`; never `--force` and never `-D` (a refusal means unmerged work: report it and leave it).
- **PR open or closed unmerged:** keep the integration worktree and branch. Offer to remove only ticket worktrees whose branch is already merged into the integration branch (`git -C <integration worktree> branch --merged kinetic/<run-id>/integration`).

Never remove the run directory; it holds the state, reports, reviews and docs. If the user declines, say the run can be cleaned up later by re-reading this step.

## Reference

### Implementation vs Review

All work goes through two stages. The implementation agent has the most **context pressure**: exploration, writing code, debugging. The review agent has the least: it receives a diff, so no exploration is needed. Hence the review agent should impose coding standards, not the implementation agent.

### Files

- Instruction file (the steering file retro's proposals target): the first file in the harness profile's instruction list that exists in the repo. `kinetic harness` prints the list under `Instruction files:` in the order the harness reads them — Claude Code: `CLAUDE.md` then `AGENTS.md`; Codex, OpenCode and Devin: `AGENTS.md` first (`CLAUDE.md` second where listed). Check per repo; propose edits to that file only. It is pushed to the context window of any agent in the repo: use incredibly sparingly, usually only for **navigation pointers** to other files.
- `CODING_STANDARDS.md`: read during review, not implementation. Add **navigation pointers** to docs folders if it grows past about 1,000 lines.
- Docs: reference files pointed to by other files. Look for existing docs before writing new ones.
- Skills: for docs (their description enters the agent's context window) or user-invoked commands.

Adapted from mattpocock/skills (retro), MIT License.
