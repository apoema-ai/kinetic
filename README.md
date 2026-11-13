# kinetic

kinetic is a plugin that drives a software change from idea to draft PRs across one or more repositories: grill the idea, write a spec, split it into tickets with typed dependency edges, build each ticket with an isolated implementer, review, ship, and run a retro. It runs inside Claude Code and Devin CLI (Codex CLI and OpenCode support is in progress).

The split of work is deliberate:

- **Scripts** (`scripts/kinetic/`, Python 3.9 stdlib, no LLM calls) own every deterministic decision: run state, the dependency graph, which tickets are ready, merge order, verify results.
- **Skills and agents** do the judgment work: interviewing, writing specs and tickets, implementing, reviewing, writing PR bodies.
- **Hooks** enforce the rules no prompt should be trusted with: no writes outside the run, no pushes to protected branches, no "done" with unverified edits.

It merges ideas from three plugins: Matt Pocock's skills (grill, spec, tickets, tdd, PR and retro writing), superpowers (subagent-driven development with per-task review) and dev-fleet (hook-enforced safety, multi-repo coordination, architecture review). `docs/sdlc-plugin-comparison.md` explains what each contributes; `docs/specs/kinetic-sdlc-pipeline-design.md` is the design.

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [How a run flows](#how-a-run-flows)
- [Lanes and entry points](#lanes-and-entry-points)
- [Example runs](#example-runs)
- [Approval gates](#approval-gates)
- [The build loop](#the-build-loop)
- [Ship: what the PRs look like](#ship-what-the-prs-look-like)
- [Trackers](#trackers)
- [Human tickets](#human-tickets)
- [Relationship types](#relationship-types)
- [The local board and drift](#the-local-board-and-drift)
- [The PR template override](#the-pr-template-override)
- [Commands](#commands)
- [Skills and agents](#skills-and-agents)
- [Configuration](#configuration)
- [Where state lives](#where-state-lives)
- [What the hooks enforce](#what-the-hooks-enforce)
- [Recovery and troubleshooting](#recovery-and-troubleshooting)
- [Code layout](#code-layout)
- [Tests](#tests)
- [Status and known limitations](#status-and-known-limitations)
- [License](#license)

## Install

Requirements: macOS or Linux, Python 3.9+, `git`, and `gh` authenticated to GitHub. Jira mode also needs the Atlassian MCP server; GitHub issues mode needs `gh` with issue access; Linear mode needs a Linear MCP server.

For local use, install from a checkout. Claude Code:

```
<path-to-kinetic>/bin/kinetic install --harness claude
claude --plugin-dir <path-to-kinetic>
```

Devin CLI:

```
<path-to-kinetic>/bin/kinetic install --harness devin
```

Codex CLI:

```
<path-to-kinetic>/bin/kinetic install --harness codex
```

OpenCode:

```
<path-to-kinetic>/bin/kinetic install --harness opencode
```

`kinetic install` links `kinetic` onto your PATH (`~/.local/bin` — make sure that directory is on your PATH), records the harness and clone in `~/.config/kinetic/settings.json`, and writes an install manifest that `doctor` checks for staleness. Re-run it after `git pull`; `kinetic install --harness <h> --uninstall` removes everything it wrote. On Claude Code, plugin registration itself (`claude --plugin-dir`) stays manual; on Devin CLI the installer runs `devin plugins install --local <clone>` itself (skills appear as `/kinetic:<name>`) and writes Devin-format hooks into `~/.config/devin/config.json`, preserving any foreign entries. Devin support is unverified until the manual checklist in `docs/smoke/devin.md` has been run (it also settles whether Devin double-registers the clone's `hooks/hooks.json`).

On Codex CLI the installer is file generation only: it writes `kntc-<name>` stub skills under `~/.agents/skills` (user-only skills get an `agents/openai.yaml` sidecar with `policy.allow_implicit_invocation: false`), agent definitions under `~/.codex/agents/*.toml` with the tier resolved to `model`/`model_reasoning_effort` (override via `tiers.codex` in `settings.json`), and merges kinetic's hooks into `~/.codex/hooks.json`, preserving foreign entries. Codex gates hooks behind interactive trust: after install, open Codex and run `/hooks` to review and trust kinetic's hooks — they stay inactive until trusted, and `kinetic doctor` fails its `hooks-trusted` check until the `trusted_hash` state matches. Codex support is validated by the manual checklist in `docs/smoke/codex.md`. Known Codex limitations: per-agent tool allow-lists are not honoured (the `tools:` frontmatter has no Codex agent equivalent), and the write-op/deploy confirmation hooks only fire on tool names matching `mcp__.*` patterns — verify MCP tool naming during the smoke run.

On OpenCode the installer is also file generation only: it writes flat `kntc-<name>.md` stub skills under `~/.config/opencode/skills` (user-only skills carry `disable-model-invocation: true`, which OpenCode honours natively), markdown agents under `~/.config/opencode/agents/*.md` with `mode: subagent`, the tier resolved to `model` (override via `tiers.opencode` in `settings.json`), and `permissions` deny rules translated from each agent's `tools:` allow-list, and drops a dependency-free TypeScript plugin at `~/.config/opencode/plugins/kinetic.ts` that forwards tool/session events to the Python hooks — deny by throwing in `tool.execute.before`, ask via `permission.evaluate`, edit recording via `execute.after`, orientation via the session `context` hook, and a bounded verify re-prompt on `experimental.idle`. OpenCode file-drops plugins: no `opencode.json` edit and no trust step. OpenCode support is validated by the manual checklist in `docs/smoke/opencode.md`; known limitations: the idle re-prompt is best-effort (the `experimental.idle` API is experimental and bounded to three rounds per session), so `verify-before-stop` stays Instructed there while `verify`/`ship` refusing stale verify is Enforced at the CLI layer on every harness.

Optional companions that kinetic uses when present and falls back without: the `resolving-merge-conflicts` skill and the `superpowers` and `dev-fleet` plugins, installed wherever the harness keeps skills and plugins (`~/.claude/skills` and `~/.claude/plugins` on Claude Code; `~/.config/devin/skills` or `~/.agents/skills` and `devin plugins install` on Devin CLI). `/kinetic:doctor` reports which are missing.

## Quick start

1. `/kinetic:init ~/code/api ~/code/web` (or `/kinetic:init` alone, from inside a repo or a folder of repos) registers the repos, detects each one's verify command, asks for the tracker (Jira, GitHub, Linear, local or other) and writes `~/.config/kinetic/`. It ends by running doctor.
2. `/kinetic:run "let partners export statements as CSV"` (or a Jira key, or a path to a spec) starts a run. kinetic picks a lane, says why in one line, and lets you override it.
3. Answer the grill questions, approve the spec, approve the ticket breakdown. From there implementers work in the background; you are asked only when one needs a decision.
4. Approve the ship gate. kinetic pushes the integration branches and opens one draft PR per repo, in merge order.
5. The retro presents improvement candidates and drafts a runbook and release notes under the run directory.

At any point `/kinetic:status` shows where the run is, and `/kinetic:ask` prints the next step.

## How a run flows

```text
  idea / Jira key / spec
          |
       [intake] -- pick lane when the repos are known
          |
       [grill] -- interview; GLOSSARY.md and ADR drafts in <run_dir>/docs/
          |
     [discover] -- candidate repos, approved sources, worktrees; final lane
          |
     [specify] -- spec_lint must pass ---------------> GATE: spec
          |
   [decompose] -- slices, per-repo tickets, typed edges
          |      graph validate must be clean ------> GATE: breakdown (records the grant)
          |
       [build] -- frontier -> implementer per ticket (background, own worktree)
          |      -> DONE only with a passing verify on record
          |      -> spec + standards reviewers -> scoped fix rounds -> merge into integration
          |      -> pin downstream repos on snapshot edges
          |
      [review] -- architecture and security review per repo, fix tickets
          |      verify every changed repo ----------> GATE: ship
          |
       [ship] -- merge order, PR bodies, draft PRs (push and PR hooks confirm)
          |
       [retro] -- retro, runbook.md, release-notes.md, cleanup offer
          |
        [done]
```

`/kinetic:run` is the only orchestrator. It sets the phase in state before each step, reads the phase skill and follows it. No skill calls another skill and no subagent dispatches another subagent.

## Lanes and entry points

| Lane | When | Phases |
|---|---|---|
| `quick` | One small ticket, one repo known at intake, no design decisions | intake, discover, build, review, ship, retro |
| `feature` | One repo, needs a spec | grill, discover, specify, decompose, build, review, ship, retro |
| `epic` | Several repos | all phases; per-repo integration branches, typed edges |

The quick lane has no grill, spec or decompose phase. Its breakdown gate is a single question that also asks which seams the tests may use, because a background implementer has no one to ask.

A run starts at the first missing artifact:

| You have | The run starts at |
|---|---|
| An idea or a bare ticket | grill |
| A spec, no tickets | discover |
| A spec and tickets with edges | build |
| One small ticket, no spec | the quick lane |

A spec brought in from outside still goes through the spec gate, and tickets brought in still go through the breakdown gate. `--from build` (and `/kinetic:implement <ref>`) skips straight to build for an already specified ticket; the breakdown gate still applies.

## Example runs

These walk through one run per lane. Repo names, ticket text and commands are illustrative; the phases, gates, ids, branches and paths follow what kinetic does. Each example assumes local tracker mode and `workspace_root` `~/workspace/kinetic-runs`, so the run directory is `~/workspace/kinetic-runs/<run-id>/`.

### Quick lane: one small fix in one repo

```
/kinetic:run "api: reject statement exports with an end date before the start date"
```

1. **Intake.** kinetic finds one repo in play (`api`) and no design decisions: "quick lane: one small ticket in api, no spec needed." You can override it. Run id: `reject-inverted-export-dates-2026-11-11`.
2. **Breakdown gate (one question).** kinetic registers the single ticket `01-api-reject-inverted-dates` with no blockers and asks you to approve it. The question spells out the grant and asks which test seams the implementer may use, for example "the export request validator, through its public validate method". Your answer goes into `issues/01-api-reject-inverted-dates.md`.
3. **Build.** The integration worktree `worktrees/api` is created on branch `kinetic/<run-id>/integration`. The ticket gets `worktrees/api-01-api-reject-inverted-dates` on `kinetic/<run-id>/01-api-reject-inverted-dates`. One implementer writes the failing test, the fix and runs `mvn -q verify`, then reports `DONE`. The spec and standards reviewers check the diff, and the ticket merges into the integration branch.
4. **Review.** Architecture and security review run on `api` if those skills are installed. `api` is verified again.
5. **Ship gate, then ship.** You see the branch, base `main` and the passing verify. On approve, kinetic opens one draft PR in `api`, titled `<run-id>: <title>` (local mode has no Jira key).
6. **Retro.** It presents improvement candidates for the repo and its checks, ordered by severity, and drafts `docs/runbook.md` and `docs/release-notes.md` for you to review.

Starting from a ticket file instead: `/kinetic:implement ~/notes/fix-dates.md` registers that one ticket and copies the file to `issues/` before dispatch.

### Feature lane: one repo, needs a spec

```
/kinetic:run "web: let partners download their monthly statement as CSV"
```

1. **Intake.** One repo (`web`), but there are design choices to settle, so: "feature lane: one repo, needs a spec."
2. **Grill.** An interview, one question at a time: which partners can download, which columns, how large a month gets, what must never appear in the file (threat model), how fast it must be (non-functional requirements). Agreed terms go into `docs/GLOSSARY.md`; a hard-to-reverse choice, such as "generate on request rather than nightly", becomes an ADR draft in `docs/adr/0001-on-request-csv.md`.
3. **Spec, then spec gate.** `spec.md` is written and must pass `spec_lint` (non-empty Threat model, Non-functional requirements and Acceptance criteria sections). You approve it, or revise and see it again.
4. **Tickets, then breakdown gate.** Two vertical slices, each a ticket in `web`:
   - `01-web-csv-endpoint`, no blockers;
   - `02-web-download-button`, blocked by `01-web-csv-endpoint` with a `merge` edge.

   `graph validate` must be clean before you see the list and approve the grant.
5. **Build.** Round 1 dispatches only `01-web-csv-endpoint` (one implementer per repo at a time). After it is reviewed and merged, round 2 cuts the worktree for `02-web-download-button` from the integration branch, so it already contains the endpoint.
6. **Review, ship gate, ship, retro.** As in the quick lane: one draft PR in `web`, whose body lists both tickets.

### Epic lane: several repos with typed edges

```
/kinetic:run INV-4321
```

Here the tracker is Jira, so ticket ids are Jira keys and the run id is `INV-4321`.

1. **Intake.** kinetic reads the Jira issue. It names only `api`, so the repo set is not known yet: provisional `feature` lane, start at the grill.
2. **Grill, then discover.** The grill settles what the change is and names the interface `StatementClient.export`. Discover asks once: use the saved base folder `~/code`, any other source, and may it search the GitHub org `acme`? It scans `~/code`, and a code search for `StatementClient.export` finds `statement-client` (a library) and `web`. You confirm all three; discover cuts their integration worktrees and sets the lane: "Epic lane: three repos."
3. **Spec.** As in the feature lane, but the spec also covers how the repos interact. It is published as a Jira issue under project `INV`, and its key is noted at the top of `spec.md`. Spec gate.
4. **Tickets, then breakdown gate.** One slice, with one child ticket per repo, linked with Jira "blocks" links and edge labels:

   | Ticket | Repo | Blocked by |
   |---|---|---|
   | INV-4322 | statement-client | none |
   | INV-4323 | api | INV-4322 (`snapshot`) |
   | INV-4324 | web | INV-4323 (`merge`) |

   `INV-4322` produces `StatementClient.export`, which `INV-4323` consumes; `graph validate` would reject the breakdown if `INV-4323` were not blocked by `INV-4322`. The `snapshot` edge is allowed because `statement-client` has `publish_snapshot` and `api` has `pin` in `repos.json`. Without them, the decompose phase would use a `merge` edge. You approve the breakdown and the grant.
5. **Build.** Each repo has its own integration branch `kinetic/INV-4321/integration`, cut at discover.
   - Round 1: only `INV-4322` is ready. Its implementer adds the client method. After review it merges into `statement-client`'s integration branch, and `kinetic.gitops pin` publishes the snapshot and pins `api` to it.
   - Round 2: `INV-4323` is ready. Its worktree is cut from `api`'s integration branch, which now carries the pin, so the implementer builds against the new client.
   - Round 3: once `INV-4323` merges into `api`'s integration branch, `INV-4324` starts in `web`.

   If an implementer returns `NEEDS_DECISION` (say, "paginate the export or stream it?"), you answer once. The answer is recorded as a ruling and the same implementer resumes.
6. **Review.** Architecture and security review per repo. A confirmed finding in `api` becomes the fix ticket `api-review-1`, built through the same loop. Every changed repo is verified again.
7. **Ship gate, then ship.** The merge order is `statement-client, api, web`. kinetic opens three draft PRs in that order, titled `INV-4321: <title>`. `api`'s PR lists the `statement-client` PR under Depends on, and has a warning that its snapshot pin must move to a released version before merge. After the last PR exists, the first two are updated so their Related PRs list all three.
8. **Retro.** The runbook gives the rollout and rollback order across the three repos. The release notes call out the pin and the new client version.

Starting from an existing spec instead: `/kinetic:run ~/specs/csv-export.md` starts at discover, then the spec gate and tickets.

## Approval gates

Three gates, each asked with a multiple-choice question and recorded in state (`gates`). A rejected gate sends the run back one phase with your feedback; the run never advances past an unapproved gate.

| Gate | When | What you see |
|---|---|---|
| `spec` | After the specify phase | The spec location and a three-line summary. The spec must already pass `spec_lint`. |
| `breakdown` | After tickets | Every ticket with its repo and blockers by edge type. Approving records the **grant**. |
| `ship` | After review | Per repo: integration branch, base branch, merge order, latest verify result. |

The grant is what the build agents may do without asking again: commit and push to ticket branches, make Jira transitions, open draft PRs. It never covers pushes to `main`, `master` or `Release*`, force-push after review, deploys, or production data writes. A hook denial is final: git pushes and `gh pr create|merge|edit|ready` are hook-confirmed (as are Atlassian MCP writes); other `gh pr` writes (close, comment, review), `gh issue`, `gh label` and `gh api` tracker writes, and other MCP tracker writes such as Linear, are covered only by the grant.

## The build loop

### Branches and worktrees

Each repo gets an **integration branch** `kinetic/<run-id>/integration`, checked out at `<run_dir>/worktrees/<repo>` by the discover phase. Until the breakdown gate is first approved, everything under `<run_dir>/worktrees/` is read-only (isolation hook). Once given, the grant stays: rejecting a re-asked breakdown gate later does not make the repos read-only again. Each ticket gets its own branch `kinetic/<run-id>/<ticket-id>` and worktree `<run_dir>/worktrees/<repo>-<ticket-id>`, cut from the integration branch at dispatch time, so it already contains the work of the tickets it depends on.

### Dependency edges

Tickets block each other with exactly three edge types (in Jira, a "blocks" link plus a label `edge:snapshot`, `edge:merge` or `edge:release`):

| Edge | The downstream ticket may start when | Example |
|---|---|---|
| `snapshot` | the upstream repo has published a snapshot build and the downstream repo is pinned to it | `web` consumes a client library `api` publishes |
| `merge` | the upstream ticket is merged into its integration branch | a second ticket in the same repo builds on the first |
| `release` | the upstream version is actually released (marked by hand) | a consumer that can only use a released artifact |

`snapshot` edges need `publish_snapshot` and `pin` configured for the repos involved; without them the decompose phase uses `merge` edges instead.

### Interfaces

Each ticket also lists the interfaces it `produces` and `consumes` (an endpoint, a client method, an event, a schema), with one stable name per interface, such as `StatementClient.export`. `graph validate` treats a ticket that consumes what another ticket produces, without being blocked by it directly or transitively, as an error: it would start before what it needs exists. An interface no ticket produces is a warning shown at the breakdown gate, to confirm it already exists in the code.

### Rounds

1. `kinetic.frontier` lists the ready tickets: blockers satisfied, at most 3 running at once and at most 1 per repo.
2. Each ready ticket gets its ticket file (`<run_dir>/issues/<id>.md`), its worktree and status `running`, then all are dispatched in one message as background `implementer` agents. Each implementer follows `tdd` and saves the failing test run as RED evidence, reviews its own diff, runs the repo's verify command through `kinetic.verify` (doing a root-cause pass if it fails), and writes a report with a status: `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `NEEDS_DECISION` or `BLOCKED`.
3. On `DONE`, the ticket is marked done only if `set-ticket` finds a passing verify for it newer than its last edit; a report is a claim, the verify record is the evidence. Then the `spec-reviewer` (which also checks the RED evidence matches an acceptance criterion) and the `standards-reviewer` review the ticket's diff against the integration branch.
4. Confirmed findings start **fix rounds**, at most 3: rounds 1 and 2 resume the same implementer (it keeps its context), round 3 is a fresh implementer on opus. After each round the `fix-reviewer` checks only the fix: each finding ADDRESSED or NOT, plus new breakage in the fix. Issues outside the fix are saved for the integration review instead of extending the loop. Findings still open after round 3 are adjudicated: blocking ones go to you, the rest are recorded as rulings.
5. The ticket branch is merged into the integration branch (conflicts use `resolving-merge-conflicts` when available, otherwise you are asked). Downstream repos on a `snapshot` edge are pinned to the new snapshot.
6. On `NEEDS_CONTEXT` the orchestrator answers from state, config, the spec or the ticket and resumes the implementer; you are asked only if it cannot. On `NEEDS_DECISION` or `BLOCKED` you are asked, the answer is recorded as a ruling, and the same implementer resumes.

If the frontier is empty while tickets are still `todo` and nothing is running, the run is stalled on edges that will not clear by themselves. kinetic shows each waiting edge and asks whether to change its type, mark a release, or stop; it never dispatches around an edge.

Ticket statuses: `todo`, `running`, `done`, `done_with_concerns`, `needs_decision`, `blocked`, `merged`, `released`.

### Review phase

The `integration-reviewer` (opus) always runs once for the whole run. It reads every repo's integration branch against its base and looks for what no per-ticket review can see: contracts that disagree across repos, wiring that was never connected, tickets that conflict once merged, acceptance criteria no ticket fully delivered, and changes that are unsafe in the merge order. In addition, for each repo, `dev-fleet:architecture-review` and `/security-review` run when available (kinetic says which ran). Confirmed findings become fix tickets named `<repo>-review-N` that go through the same build rounds. Every changed repo is verified again; a failing verify blocks the ship gate.

## Ship: what the PRs look like

The ship phase gets the merge order from `kinetic.gitops merge-order` (upstream repos first). It reuses an open PR already on the branch, skips a repo whose PR was merged or closed, shows one table (repo, branch, title, base, depends on), then pushes each integration branch and opens a **draft** PR. PR titles are `<KEY>: <title>`, where KEY is the Jira key or the run id.

Every PR body has the same section order, so reviewers read every PR of a run the same way:

```markdown
### Tickets:
- <KEY or local ticket id> - <ticket title>

### Description:
<2-4 lines: what changes in this repo and why>
Merge in this order: api, web

#### Design decisions
| Decision | Why |
|---|---|

#### Architecture
<ASCII diagram, * = changed in this PR>

### Attention points:
> [!WARNING]
> <merge blockers: snapshot pins to revert, PRs that must merge first>

- **Risk:** <one-way or two-way door; blast radius>
- **Evidence:** <verify command and result from the run's verify records>
- **Unverified / gaps:** <...>

### Manual steps:
- <ref> - <title> (done by human: <note>)

### Ships with:
<PRs in other repos that must merge and deploy together>

### Related PRs:
| PR | Merge order | Relationship |

### Depends on:
- [ ] <org>/<repo>#<n>
```

Bodies are written for developers: no lists of files touched, every design decision with its reason (or flagged as unverified), evidence taken from the recorded verify runs rather than invented. Each body is re-read as a teammate who has seen neither the diff nor the tickets before it is saved. Once all PRs exist, earlier PRs are updated so their Related PRs list every sibling. No CI directive lines are added; Depends on and the merge order carry the dependency.

## Trackers

The tracker is where tickets live. Pick it once in `~/.config/kinetic/settings.json` (user level only; a repo cannot switch it) with `/kinetic:init`, or edit the file:

| `tracker` | Needs | Settings |
|---|---|---|
| `jira` | Atlassian MCP | `jira_project`, `slice_issue_type`, `child_issue_type` |
| `github` | `gh` | `github_repo` |
| `linear` | a Linear MCP server | `linear_team` |
| `local` (the default) | nothing | none |
| `other` | whatever you describe | `tracker_description` |

Each tracker is one prose file, `trackers/<name>.md`, that tells the skills how to create a ticket, link blockers, set a status and so on in that tracker. No Python talks to a tracker, so adding one means adding one adapter file. Skills use roles, not tracker words: `names.kind.human` (the label or type for a human ticket), `names.edge.merge`, `names.after`, `names.ships_with`, `names.related` and `names.status.<role>`.

To rename any of these for your workspace, override them in `settings.json`:

```json
{
  "tracker": "jira",
  "tracker_settings": { "jira_project": "INV", "slice_issue_type": "Story", "child_issue_type": "Sub-task" },
  "tracker_names": { "kind": { "human": "manual" }, "status": { "done": "Closed" } }
}
```

`tracker_names` is merged key by key over the adapter's defaults; a missing role is an error. The top-level `jira_project`, `slice_issue_type` and `child_issue_type` keys from 0.2.0 are still read. `kinetic tracker resolve` prints what kinetic resolved. kinetic state stays authoritative: remote trackers are written to, never read back.

## Human tickets

Some steps only a person can do: request a credential, flip a flag in a console, get a sign-off. A ticket with `kind: human` models it. It has no repo, is never dispatched to an implementer, and sits in the graph like any ticket, so other tickets can be blocked by it.

- **Waiting on you.** `/kinetic:status` and the board list human tickets whose blockers are satisfied under "Waiting on you".
- **Only human work left.** When nothing is ready or running, agent tickets remain un-merged, and every remaining ticket is human or behind a human ticket you can act on, the run pauses and says so instead of reporting a stall; say `ship` to continue with those human tickets open; ship then lists the agent tickets still behind them as not merged and makes them merge blockers. The build loop ends once every agent ticket is merged, so human tickets still open then are carried into review and ship as open items.
- **`human-done`.** `kinetic state human-done --run <run_dir> --id <id> [--note "..."]` marks it done. `set-ticket` refuses `done` on a human ticket. An edge onto a human blocker is satisfied when it is `done`, whatever its edge type.
- **`NEEDS_HUMAN`.** An implementer that hits a step only a person can do reports `NEEDS_HUMAN`. kinetic creates a new human ticket, blocks the original on it and parks the original until you finish it. The original keeps its repo and worktree.
- **Ship.** Ship still opens draft PRs while a human ticket is open; open human tickets that block a repo's tickets appear as a merge blocker under Attention points and in Manual steps.

## Relationship types

Besides `blocked_by` (with the `snapshot`, `merge` and `release` edge types), tickets can carry three softer relationships:

| Field | Meaning | Effect |
|---|---|---|
| `after` | Prefer to build this after another ticket | Breaks ties in build order only; never blocks; a soft cycle never blocks either and is reported by `graph validate` as a warning only |
| `ships_with` | A group name shared by tickets that must be released together | Merge order puts the group's repos next to each other when blockers allow; PR bodies get a "Ships with" section |
| `related` | Context only | Listed in the ticket; a related human ticket also appears in the PR's Manual steps |

`graph validate` reports unknown `after` or `related` ids, an `after` that contradicts a `blocked_by`, and a `ships_with` group of one ticket. `kinetic gitops ships-with --run <run_dir>` prints the groups by repo. Tickets written by 0.2.0 need no migration: missing fields default to `kind` agent and empty relationships.

## The local board and drift

In local mode tickets are markdown files under `<run_dir>/issues/`, and `issues/README.md` is a board: "Waiting on you" first, then every ticket with its kind, status and blockers. kinetic state is the source of truth; the files are a view of it.

- `kinetic board header --run <run_dir> --id <id>` writes a ticket file's header (Status, Type, Repo, Slice, Blocked by, After, Ships with, Related, Assignee). Comments below the header are kept. Assignee is derived (human: the user, agent: the implementer), not stored.
- `kinetic board render --run <run_dir>` rewrites the board.
- `kinetic board drift --run <run_dir>` lists files that disagree with state. A file written by hand shows drift until its first `header`. If you mark a human ticket done by editing its file, kinetic sees the drift and asks before applying it.

## The PR template override

Ship fills one template for every PR. The default is `templates/pr-body.md`. To use your own, set `pr_template` to a file path, in `settings.json` for every repo or in a repo-root `.kinetic.json` for one repo. The first of repo `.kinetic.json`, `settings.json` and the plugin default wins; a relative path resolves against the directory of the file that set it, and a configured file that is missing is an error. `kinetic tracker pr-template --repo <path>` prints the path used. Placeholders are `<<TITLE_KEY>>`, `<<TICKETS>>`, `<<DESCRIPTION>>`, `<<DESIGN_DECISIONS>>`, `<<ARCHITECTURE>>`, `<<ATTENTION_POINTS>>`, `<<MANUAL_STEPS>>`, `<<SHIPS_WITH>>`, `<<RELATED_PRS>>` and `<<DEPENDS_ON>>`; the filled placeholders are kept in `<run_dir>/pr/<repo>.placeholders.md` for the backfill once all PRs exist.

## Commands

| Command | What it does |
|---|---|
| `/kinetic:run <JIRA-KEY\|idea\|spec-path> [--from build]` | Orchestrates a run end to end, stopping at each gate |
| `/kinetic:implement <JIRA-KEY\|ticket-file\|spec-path>` | Alias for `run --from build` on an already specified ticket |
| `/kinetic:init [repo-path ...]` | One-time setup of repos, verify commands, snapshots, tracker; safe to re-run |
| `/kinetic:doctor` | Read-only health check with a one-line fix per failure |
| `/kinetic:status [run-dir]` | Phase, tickets, frontier and gates of a run (the active one by default) |
| `/kinetic:ask` | The lanes and the next step `next_step` computes for the active run |
| `/kinetic:cleanup [run-dir]` | Removes the run's local worktrees and branches whose work is merged, after one confirmation |

## Skills and agents

| Name | Kind | Model | Role |
|---|---|---|---|
| `run` | command | sonnet | The orchestrator: lanes, gates, phases, build loop |
| `implement` | command | sonnet | `run --from build` |
| `init`, `doctor`, `status`, `ask` | commands | sonnet, haiku, haiku, haiku | Setup and read-only views |
| `cleanup` | command | sonnet | Removes merged worktrees and branches of a run |
| `grill` | phase skill | inline | Interview covering threat model and non-functional requirements; keeps the glossary and ADR drafts |
| `discover` | phase skill | inline | Finds the run's repos from approved sources (base folders, your sources, the GitHub org), confirms them with you, registers them and cuts their worktrees |
| `specify` | phase skill | inline | Spec with testing decisions, linted by `spec_lint`, published to Jira or `<run_dir>/spec.md` |
| `decompose` | phase skill | inline | Vertical slices, per-repo tickets, typed edges, validated by `graph validate` |
| `ship` | phase skill | inline | PR bodies, merge order, draft PR set |
| `retro` | phase skill | inline | Retro, runbook, release notes |
| `tdd` | skill | sonnet | Test-first loop the implementer preloads (`skills: [tdd]`) |
| `implementer` | agent | sonnet | One ticket in its own worktree; tools: Read, Edit, Write, Grep, Glob, Bash |
| `spec-reviewer` | agent | opus | Read-only: does the diff do what the ticket asks; is the RED evidence real |
| `standards-reviewer` | agent | opus | Read-only: does the diff meet the repo's standards |
| `fix-reviewer` | agent | sonnet | Read-only, scoped: is each finding fixed, did the fix break anything |
| `integration-reviewer` | agent | opus | Read-only, whole run: cross-repo contracts, wiring, ticket interactions, merge order |

Phase skills run inline in the orchestrator's session, so their `model:` field has no effect; they use whatever model the session runs. Reviewers have no Write tool: they return text and the orchestrator saves it under `<run_dir>/reviews/`.

## Configuration

All user config lives in `~/.config/kinetic/`; `/kinetic:init` writes it and never writes inside a repo.

`repos.json`, one entry per repo (`verify` is required):

```json
{
  "api": {
    "path": "/Users/me/code/api",
    "verify": "mvn -q verify",
    "publish_snapshot": "mvn -q deploy -DskipTests",
    "pin": "./scripts/pin-api.sh \"$KINETIC_UPSTREAM_REF\"",
    "base_branch": "main"
  },
  "web": {
    "path": "/Users/me/code/web",
    "verify": "npm test"
  }
}
```

- `verify`: the command that proves the repo works; its exit code is the verdict.
- `publish_snapshot`: builds and publishes a snapshot other repos can consume.
- `pin`: runs in the downstream repo and points it at the upstream snapshot; it reads `KINETIC_UPSTREAM_REF`.
- `base_branch`: the branch PRs target (default `main`).

A repo-root `.kinetic.json` with the same keys overrides the central entry key by key:

```json
{ "verify": "make test" }
```

`settings.json`:

```json
{
  "tracker": "jira",
  "tracker_settings": { "jira_project": "INV", "slice_issue_type": "Story", "child_issue_type": "Sub-task" },
  "workspace_root": "~/workspace/kinetic-runs",
  "repo_roots": ["/Users/me/code"],
  "github_orgs": ["acme"]
}
```

`repo_roots` (folders whose child repos discovery may scan) and `github_orgs` (orgs discovery may search) are written by the discover phase when you approve them, and offered as defaults on the next run. Missing keys mean none.

The 0.2.0 top-level `jira_project`, `slice_issue_type` and `child_issue_type` keys are still read. With `"tracker": "local"` (or no `tracker` key) tickets are files under `<run_dir>/issues/`. See [Trackers](#trackers) for the other trackers, `tracker_settings` and `tracker_names`, and [The PR template override](#the-pr-template-override) for `pr_template`.

## Where state lives

```text
<workspace_root>/<run-id>/
  state.json            run state (flock-guarded, written atomically)
  spec.md               the spec (local mode, or a copy noting the Jira key)
  discovery.md          repos chosen by discover, with reasons and sources
  docs/                 GLOSSARY.md, adr/, runbook.md, release-notes.md
  issues/<id>.md        ticket files (local mode, quick lane, fix tickets)
  reports/<id>.md       implementer reports (and <id>-fix-N.md)
  reviews/<id>-<axis>.md  reviewer findings
  logs/                 verify logs
  pr/<repo>.md          PR bodies
  worktrees/<repo>      integration worktree per repo
  worktrees/<repo>-<id> ticket worktree per ticket
~/.config/kinetic/active-run   absolute path of the active run dir; absent means no run
```

`kinetic state load --run <run_dir>` prints the whole state: lane, phase, tickets, slices, repos, gates, rulings, verify results and the owning session.

## What the hooks enforce

| Hook | Event | Rule |
|---|---|---|
| `completion_gate` | Stop | Blocks "done" while a repo has edits newer than its last passing verify, and names the command to run |
| `isolation` | PreToolUse on file writes | Denies writes outside the registered repos and the run directory |
| `confirm_write_ops` | PreToolUse on Bash and GitHub/Jira MCP writes | Denies `git push` to `main`, `master` or `Release*`; asks before other pushes, `gh pr create|merge|edit|ready` and Jira or GitHub MCP write calls |
| `confirm_deploy` | PreToolUse on deploy and Tekton-trigger MCP calls | Asks first |
| `record_edit` | PostToolUse on file writes | Records edits so the Stop gate can compare them with verifies |
| `claim_run` | PostToolUse on Bash | Records the session that wrote the active-run pointer as the run's owner |
| `orient` | SessionStart | Tells a new session about the active run and the next step |

The run-scoped hooks (isolation, record_edit, completion_gate) act only in the session that owns the run and on calls whose working directory is inside the run directory, so other Claude sessions on the machine are unaffected. The push and deploy hooks always apply.

## Recovery and troubleshooting

- **Resume after a crash or in a new session.** Run `/kinetic:run` again. It finds the active run, rewrites the pointer (which claims the run for the new session), and resumes at the recorded phase. Recorded gates stay approved. For a ticket still `running` with no report, kinetic shows what its worktree holds and asks whether to re-dispatch an implementer there or set it back to `todo`.
- **A crash during a fix round.** Recovery cannot yet tell a dead fix agent from a finished first round; check the report's latest `## Fix round` section and `<run_dir>/reviews/<id>-fix-N.md` by hand.
- **`set-ticket` refuses `done`.** The ticket has no passing verify newer than its last edit. Re-run verify in its worktree (`kinetic verify --run <run_dir> --repo-name <repo> --repo-path <worktree> --ticket <id>`) or resume the implementer.
- **Clean up after merge.** The retro offers to remove ticket and integration worktrees and branches whose PRs merged, listing them and asking first. It never force-removes and never deletes the run directory.
- **Abandon a run.** `rm -f ~/.config/kinetic/active-run`. The run directory stays for reference.
- **A hook denied something.** A denial is final for that action. Read the reason: an isolation denial names the allowed roots; a push denial means the target is a protected branch.
- **`/kinetic:init` is denied writing config.** You are in the session that owns the active run; run it from another session.
- **The run is stalled.** The frontier is empty with tickets still `todo`. kinetic shows the waiting edges; usually a `snapshot` edge between repos without `publish_snapshot`/`pin`, or a `release` edge nobody has marked. Mark a release with `kinetic state set-ticket --run <run_dir> --id <upstream-id> --field status=released`.
- **Doctor checks:** `git` and `gh` on PATH, `gh auth status`, a readable `repos.json`, a resolvable verify command per repo, the optional companion skills and plugins, and a reminder to check the Atlassian MCP with `/mcp`.

**Upgrading an existing Claude Code install:** skills, agents and hooks now call `kinetic ...` instead of `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/scripts python3 -m kinetic.*`. After updating, run `<clone>/bin/kinetic install --harness claude` once; until then `doctor` warns and skills fall back to `python3 <plugin-root>/bin/kinetic`.

**OpenCode:** the plugin asks for confirmation on every edit or shell call when `python3` is missing or a kinetic hook crashes, rather than allowing it.

**Reviewer read-only check:** the hash covers tracked diffs and untracked files; gitignored files are not covered.

**Stale-verify guard:** on every harness (Claude included), `set-phase ship` and an approved ship gate are refused while a repo's verify is stale — this is intentional.

Run kinetic commands as `kinetic <module> ...` once installed (`kinetic root` prints the clone root). From a checkout without installing, `PYTHONPATH=<kinetic>/scripts python3 -m kinetic.<module> ...` still works.

## Code layout

```text
.claude-plugin/plugin.json   plugin manifest
skills/<name>/SKILL.md       commands and phase skills; skills/run/guides/ holds the
                             build loop, lanes, gates and recovery guides
agents/                      implementer, spec-reviewer, standards-reviewer,
                             fix-reviewer, integration-reviewer
hooks/                       hooks.json and one Python script per hook; _common.py
                             resolves the active run and its session scope
scripts/kinetic/             the deterministic core
tests/                       unittest suite, including a two-repo end-to-end fixture
docs/                        comparison, design spec, implementation plan, rulings
```

| Module | Responsibility |
|---|---|
| `state.py` | Run state: init, phase, slices, tickets, repos, gates, rulings, verify and edit stamps, owner session; flock-guarded atomic writes; CLI (whose `set-ticket` refuses `done` without a passing, current verify) |
| `graph.py` | Validates the ticket graph (missing repo except on human tickets, edge types, unknown blockers, unused slices, cycles, consumers without an edge to their producer, unknown or contradicting `after`/`related`, lone `ships_with` groups; unproduced interfaces as warnings) and gives a topological order that honours `after` |
| `frontier.py` | Ready tickets (never human): satisfied blockers, the cap of 3 running, one per repo; `waiting_on_you` and `only_human_left` for human tickets |
| `gitops.py` | `worktree`, `merge` (ticket into integration), `merge-order` across repos (ships-with neighbours kept together), `ships-with` groups, `pin` downstream repos to a snapshot, `status-hash` and `assert-unchanged` (reviewer read-only check) |
| `verify.py` | Runs a repo's verify command, logs it and records the result in state |
| `config.py` | Resolves a repo's config from `repos.json` and `.kinetic.json` |
| `detect_repos.py` | Proposes a verify command from build markers (Maven, Gradle, npm, Go, Cargo, pyproject, Makefile) |
| `tracker.py` | Resolves the tracker adapter, its settings and role names, and the PR template path |
| `board.py` | Local ticket headers, the `issues/README.md` board and the drift check |
| `doctor.py` | The health checks behind `/kinetic:doctor`, including tracker access and the PR template |
| `spec_lint.py` | Checks a spec has non-empty Threat model, Non-functional requirements and Acceptance criteria sections |
| `status.py` | Renders `/kinetic:status` |
| `next_step.py` | Computes the next step for `/kinetic:ask` and the SessionStart hook |

## Tests

```
PYTHONPATH=scripts python3 -m unittest discover -s tests -v
```

The suite covers every script module and every hook, plus an end-to-end test that drives the scripts through a two-repo run with real git repositories and a `merge` edge.

## Status and known limitations

kinetic is at 0.4.0 (see `.claude-plugin/plugin.json`); 0.4.0 adds the discover phase (repos found from approved sources, worktrees cut at discover, repos read-only until the breakdown gate) and `/kinetic:init` from the current directory; 0.3.0 adds trackers, human tickets, relationship types, the local board and the PR template override, and 0.3.1 corrects the hook wording, flags unmerged agent tickets at ship, and keeps file modes on atomic writes. The scripts and hooks are tested; the skills and agents have not yet been exercised in a live end-to-end run. `docs/plan/kinetic-v0-rulings.md` records every decision made while building it and the v0.2 backlog.

Not yet verified in a live session:

- that `kinetic` is on PATH wherever skills and agents run it;
- that `skills: [tdd]` resolves to kinetic's own `tdd` skill;
- whether subagent hook payloads carry the parent session id (the cwd rule covers implementers either way);
- the Jira, GitHub and Linear adapters against the real services: they are untested live, including whether the installed `gh` supports sub-issues and "blocked by" and which relation tools the Linear MCP exposes (the adapters have fallbacks, but no test checks them).

Known limitations:

- A bare `git push` on a protected branch only asks; it is not denied.
- `gh api` calls (including merges) pass the write-ops hook, and base branches other than `main`, `master` and `Release*` are not protected.
- Isolation cannot tell implementers apart within the run directory.
- Until a session claims the run, or when a hook payload has no session id, the run-scoped hooks act on every session.
- Hook confirmation: git pushes and `gh pr create|merge|edit|ready` are hook-confirmed (as are Atlassian MCP writes); other `gh pr` writes (close, comment, review), `gh issue`, `gh label` and `gh api` tracker writes, and other MCP tracker writes such as Linear, are covered only by the grant.
- No skill evals yet; `/kinetic:status` shows no PR health or Jira transitions.

## License

Some skills are adapted from third-party work (Matt Pocock's skills, MIT); see `THIRD_PARTY_LICENSES.md`.
