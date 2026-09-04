# Setup agent-skill config for Byond (kinetic/)

## Context

The user ran `/setup-matt-pocock-skills`, which scaffolds per-repo agent-skill configuration (issue tracker, triage labels, domain docs) so skills like `to-tickets`, `triage`, and `to-spec` know where issues live and how to read domain context.

Exploration found the working directory (`/Users/rmendes/workspace/lab`) is not a git repository and contains only `.claude/` and `kinetic/`. The real project is `kinetic/` — "Byond," a Dockerized development environment (Ubuntu + Claude Code + git + npm + Homebrew via Docker Compose). It already has mature domain docs (`CONTEXT.md`, `docs/adr/0001-0003`, `README.md`, `PLAN.md`) but, like the parent directory, has no `.git` yet — despite already having a `.gitignore`.

Confirmed with the user:
- **Target**: `/Users/rmendes/workspace/lab/kinetic`
- **Git**: initialize locally now (`git init` + initial commit); no GitHub remote is created/linked in this pass — the user will add one later themselves, after which the GitHub-based issue-tracker config below becomes usable
- **Triage labels**: skipped — the `triage` skill is not installed (absent from the available-skills list, no `triage/` folder alongside this skill)
- **Domain docs**: single-context — kinetic already follows exactly this layout (`CONTEXT.md` + `docs/adr/` at the repo root), no monorepo signals found
- **Instructions file**: `CLAUDE.md` (doesn't exist yet in kinetic/ — will be created)
- **This plan document**: after approval, moves from the harness path into `kinetic/plans/` (matches the project's existing convention — it already holds `docs-credify-tech-hld-lld-template-audit.md` there)

## Steps

### 1. Initialize git in kinetic/

```
git init
git add <all existing files>   # .gitignore already excludes .env
git commit -m "<initial commit message>"
```

No remote is added. `.gitignore` already correctly excludes `.env` (the only file that should never be committed).

### 2. Write `docs/agents/issue-tracker.md`

Based on the skill's GitHub seed template (`~/.claude/skills/setup-matt-pocock-skills/issue-tracker-github.md`), copied near-verbatim with one addition: a short note that no remote is linked yet. "PRs as a request surface" stays at its default `no` (per the skill's instructions, not raised to the user).

```markdown
# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

> **Note**: no GitHub remote is linked yet. Once you run `git remote add origin <url>` (or `gh repo create`), the `gh` commands below will resolve automatically via `git remote -v`.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
```

### 3. Write `docs/agents/domain.md`

Copy the skill's generic template verbatim (`~/.claude/skills/setup-matt-pocock-skills/domain.md`) — no repo-specific edits needed since kinetic already matches the single-context layout the template describes.

### 4. Skip triage-labels.md

Not written; `triage` skill isn't installed.

### 5. Create `kinetic/CLAUDE.md`

New file (neither `CLAUDE.md` nor `AGENTS.md` exists yet in kinetic/):

```markdown
## Agent skills

### Issue tracker

Issues live as GitHub issues (once a GitHub remote is linked). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
```

### 6. Relocate this plan document

After approval, `git mv`/`mv` this plan file from the harness path into `kinetic/plans/` with a descriptive slug (no ticket prefix — this is a ticket-less personal project). Will confirm the exact filename with the user at execution time per their renaming convention.

## Files to create/modify

- `/Users/rmendes/workspace/lab/kinetic/.git/` — new, via `git init` + initial commit
- `/Users/rmendes/workspace/lab/kinetic/docs/agents/issue-tracker.md` — new
- `/Users/rmendes/workspace/lab/kinetic/docs/agents/domain.md` — new
- `/Users/rmendes/workspace/lab/kinetic/CLAUDE.md` — new
- `/Users/rmendes/workspace/lab/kinetic/plans/<renamed-plan>.md` — this plan, relocated

No existing files (`README.md`, `CONTEXT.md`, `docs/adr/*`, `PLAN.md`, `Dockerfile`, etc.) are modified.

## Verification

- `git -C /Users/rmendes/workspace/lab/kinetic status` — clean working tree, `.env` not tracked
- `git -C /Users/rmendes/workspace/lab/kinetic log --oneline` — exactly one commit
- Read back `docs/agents/issue-tracker.md`, `docs/agents/domain.md`, and `CLAUDE.md` to confirm they match the drafts above
- Confirm no pre-existing file's content changed (diff against the initial commit should show only additions)
