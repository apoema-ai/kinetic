---
name: ship
description: Write developer-oriented PR bodies, determine cross-repo merge order, and open the set of draft PRs with gh, linking siblings and dependencies. Use at the ship phase of a kinetic run.
model: sonnet
---

# Ship

Write a PR body per repo integration branch, then open the set as **draft** PRs in merge order, wiring each PR's Depends on and Related PRs. This skill never invokes another skill and never dispatches a subagent: the orchestrator follows it inline.

The orchestrator passes `Run: <dir>` (the run directory, `<workspace>/<run-id>/`). Run scripts as `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.<module> ...`. Repo paths, integration branches and tickets are in the run state (`python3 -m kinetic.state load --run <dir>`, fields `repos` and `tickets`); `base_branch` comes from repo config (default `main`); `tracker` comes from `~/.config/kinetic/settings.json`.

## Rules

- Never push to `main`, `master` or `Release*` branches; push only the integration branch.
- Open PRs only as drafts. Do not merge any PR, mark one ready, or deploy.
- Never edit a PR that existed before this run.
- Run git and gh against an explicit repo (`git -C <repo_path>`, or from the repo path); the shell's working directory is not kept between calls.
- Write body files under `<dir>/pr/` with the Write tool, never `/tmp`: isolation denies writes outside the run directory.
- No AI attribution in commits or PR bodies. No emojis.
- The push/PR confirmation hook may prompt; that is the expected gate. A hook denial is final: report it, do not retry another way.

## Process

### 1. Order and pre-flight

```
python3 -m kinetic.gitops merge-order --run <dir>
```

It prints the ordered repo list, upstream first (and errors on a dependency cycle). For each repo, in that order:

1. `git -C <repo_path> status --porcelain`. Uncommitted changes in the integration worktree mean the build loop left something behind: stop and show them to the user.
2. `git -C <repo_path> fetch origin <base_branch>`.
3. Look up PRs already on the branch: `gh pr list --head <integration-branch> --state all --json number,url,state` (from the repo path).
   - An **open** PR is reused: record its URL, do not push or edit it. It still counts in other PRs' Depends on and Related PRs.
   - Only **merged or closed** PRs: skip the repo and report it; do not open a second PR from the same branch.
   - The lookup fails: an unknown answer is not "no PR". Show the error and ask whether to retry or skip the repo.
   - None: the repo needs a PR.

Title: `<KEY>: <title>`, where KEY is the slice's Jira key in Jira mode, else the run id, and the title is the spec's (or the quick-lane ticket's) title.

### 2. Write the bodies

For each repo that needs a PR, in merge order, read its change against the base (read-only):

```
git -C <repo_path> log origin/<base_branch>..<integration-branch> --oneline
git -C <repo_path> diff origin/<base_branch>..<integration-branch> --stat
git -C <repo_path> diff origin/<base_branch>..<integration-branch>
```

Also read the repo's tickets (state `tickets` whose `repo` is this repo, and their `<dir>/issues/<id>.md`), its newest `verify` record and log, and the bodies already written this run, to keep terminology consistent. Then write the body (layout below) to `<dir>/pr/<repo>.md` with the `<<RELATED_PRS>>` and `<<DEPENDS_ON>>` placeholders left in place.

**Review loop before saving.** Re-read the draft as a teammate who has seen neither the diff nor the tickets, fix what fails, and re-read, up to 3 rounds:

- Is it understandable without opening the code? Spell out acronyms and internal shorthand on first use; never cite IDs the reader cannot open.
- Is every "this" and "it" unambiguous, and every number labeled with what it counts?
- Does each design decision state a reason, and each attention point say what to do about it?
- Is anything claimed that the diff, tickets or verify logs do not support? Remove it or move it to Unverified / gaps.
- Is anything redundant or implementation-level? Cut it.

Do not guess a rationale. If the diff does not show why a decision was made, state the decision and its observable effect, and list it as unverified rationale for the final report.

### 3. Confirm, push, create

Show one table before the first push: repo, integration branch, title, base, PR action (create / reuse / skip), and Depends on. The ship gate approved shipping; this table lets the user catch a wrong title or base before anything leaves the machine.

Then for each repo that needs a PR, in merge order:

1. Copy the body and fill the placeholders with what is known so far (see "Depends on and Related PRs"), and write it back to `<dir>/pr/<repo>.md`.
2. Push and open the draft:

```
git -C <repo_path> push -u origin <integration-branch>
gh pr create --draft --base <base_branch> --head <integration-branch> --title "<title>" --body-file <dir>/pr/<repo>.md
```

3. Record the PR URL and number. Later repos' Depends on and Related PRs use it.

### 4. Backfill

An early PR cannot list siblings created after it. Once all PRs exist, for each PR **created in this run** whose Related PRs is now incomplete, rebuild its body from the placeholder version with the complete list, write it to `<dir>/pr/<repo>.md` and `gh pr edit <url> --body-file <dir>/pr/<repo>.md`. Skip when fewer than two PRs exist.

### 5. Report

To the orchestrator (the ship approval was already recorded at the ship gate):

| # | Repository | Status | PR |
|---|---|---|---|
| 1 | <repo> | Created / Already existed / Skipped (merged, closed, lookup failed) | <url> |

Then the merge order with edge types (`api -> web (snapshot)`), every unverified rationale so the author can fill it in before review, and any skipped upstream repo that leaves a downstream PR with a missing dependency.

## PR body layout

The section order is fixed so reviewers read every PR of a run the same way. If the repo has `.github/pull_request_template.md` with extra sections worth keeping (a checklist), keep them after Description. Use the user's domain language from `<dir>/docs/GLOSSARY.md` (or the repo's `GLOSSARY.md`).

````markdown
### Tickets:
- <KEY or local ticket id> - <ticket title>

### Description:
<2-4 lines: what changes in this repo and why, in terms of behavior and responsibility>

#### Design decisions
| Decision | Why |
|---|---|
| <what was decided> | <why this over the alternative> |

#### Architecture
```text
<ASCII diagram of the implementation architecture>
* = changed in this PR
```

### Attention points:
> [!WARNING]
> <merge blockers and temporary pins, only if any: what must happen before merge>

- **Risk:** <one-way or two-way door; blast radius narrow / moderate / wide>
- <what a reviewer or deployer must know: ordering, migrations, flags, behavior changes>
- **Evidence:** <before vs after, plus the verify command and its result>
- **Unverified / gaps:** <what is not covered or not known>

### Related PRs:
<<RELATED_PRS>>

### Depends on:
<<DEPENDS_ON>>
````

### Writing rules

- **For developers, concisely.** No coding details: no lists of files, classes touched or renamed variables; the diff shows that. Name a class or method only when it is an entry point or seam someone must know to follow the flow.
- **Tickets**: one line per ticket merged into this repo. Jira mode: the Jira key and summary. Local mode: the ticket id and its title from `<dir>/issues/<id>.md`.
- **Design decisions**: where a responsibility was placed, sync vs async, new vs reused abstraction, contract or schema shape, backward compatibility, flag vs hard switch, failure isolation. Skip a decision with no real alternative; omit the subsection for a trivial change.
- **Architecture (always included)**: a plain ASCII diagram in a `text` fence of the components this change touches, how they connect (calls, events, data reads) and the key methods or messages on the links. At most about 15 lines and 80 columns. Mark what this PR changes with `*` and keep the legend line. Show sibling repos where they sit on the other side of a link. For a flow, put its direction on the links rather than drawing a second diagram. For a small change, draw just the changed component and its neighbors. Every box and link must come from the diff or the repo; an inferred link goes under Unverified / gaps.
- **Attention points**: the alert holds merge blockers only: a downstream repo pinned to an upstream snapshot (`kinetic.gitops pin`) that must move to a released version, an upstream PR that must merge first. Risk: a two-way door can be walked back, a one-way door (destructive or hard to reverse) cannot; the blast radius is the scope of impact, such as consumer breakage or a pinned downstream repo. Evidence comes from the run's `verify` records and logs: the command, exit code and test counts as recorded, and the failing-then-passing test where the tickets show one. Never invent counts. Other bullets only when they change how someone reviews, merges or deploys: migrations and rollback, deploy ordering, incompatible contract changes, new config or flags and their defaults, behavior differences between environments.
- About 40 lines or fewer excluding the diagram. Bullets over paragraphs. Drop any section that ends up empty; never leave a blank heading.
- GitHub markdown for readability, not decoration: tables for decisions and related PRs, the alert for merge blockers only, task lists for dependencies, `<org>/<repo>#<n>` shorthand so links autolink, backticks for identifiers. Long evidence goes in `<details><summary>...</summary>`. No headings deeper than `####`.
- No CI directive lines (such as `+dep-pr` or `+deploy`); Depends on and the merge order carry the dependency.

### Depends on and Related PRs

- `<<DEPENDS_ON>>`: the PRs of the repos this repo depends on (its upstream repos in the merge order), as a task list, lowest level first. None: remove the whole section.

  ```
  - [ ] <org>/<repo>#<n>
  ```

- `<<RELATED_PRS>>`: every other PR of this run known so far that is not under Depends on, as table rows with the merge order position, the edge type and one phrase on the relationship. None yet: remove the whole section (backfill adds it later).

  ```
  | PR | Merge order | Relationship |
  |---|---|---|
  | <org>/<repo>#<n> | 2 of 3 (snapshot) | consumes the new client from this PR |
  ```

Add one line under Description in every body when there are two or more PRs: "Merge in this order: <repo>, <repo>, ...".

Door and blast radius adapted from mattpocock/skills (pr), MIT License. Layout and review loop follow investor-toolkit's open-multi-repo-prs.
