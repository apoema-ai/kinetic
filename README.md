# kinetic

kinetic is a Claude Code plugin that drives a software change from idea to draft PRs across one or more repositories: grill the idea, write a spec, split it into tickets with typed dependency edges, build each ticket with an isolated implementer, review, ship, and run a retro.

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
- [Approval gates](#approval-gates)
- [The build loop](#the-build-loop)
- [Ship: what the PRs look like](#ship-what-the-prs-look-like)
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

Requirements: macOS or Linux, Python 3.9+, `git`, and `gh` authenticated to GitHub. Jira mode also needs the Atlassian MCP server.

For local use, point Claude Code at a checkout:

```
claude --plugin-dir <path-to-kinetic>
```

Optional companions that kinetic uses when present and falls back without: the `find-ticket-repos`, `checkout-ticket-repos` and `resolving-merge-conflicts` skills under `~/.claude/skills`, and the `superpowers` and `dev-fleet` plugins (for `receiving-code-review`, `architecture-review` and `release`). `/kinetic:doctor` reports which are missing.

## Quick start

1. `/kinetic:init ~/code/api ~/code/web` registers the repos, detects each one's verify command, asks for the tracker (Jira or local) and writes `~/.config/kinetic/`. It ends by running doctor.
2. `/kinetic:run "let partners export statements as CSV"` (or a Jira key, or a path to a spec) starts a run. kinetic picks a lane, says why in one line, and lets you override it.
3. Answer the grill questions, approve the spec, approve the ticket breakdown. From there implementers work in the background; you are asked only when one needs a decision.
4. Approve the ship gate. kinetic pushes the integration branches and opens one draft PR per repo, in merge order.
5. The retro writes the run's lessons, a runbook and release notes under the run directory.

At any point `/kinetic:status` shows where the run is, and `/kinetic:ask` prints the next step.

## How a run flows

```text
  idea / Jira key / spec
          |
       [intake] -- pick lane, detect repos
          |
       [grill] -- interview; GLOSSARY.md and ADR drafts in <run_dir>/docs/
          |
       [spec] -- spec_lint must pass ---------------> GATE: spec
          |
      [tickets] -- slices, per-repo tickets, typed edges
          |      graph validate must be clean ------> GATE: breakdown (records the grant)
          |
       [build] -- frontier -> implementer per ticket (background, own worktree)
          |      -> spec + standards reviewers -> fix rounds -> merge into integration
          |      -> pin downstream repos on snapshot edges
          |
      [review] -- architecture and security review per repo, fix tickets
          |      verify every changed repo ----------> GATE: ship
          |
       [ship] -- merge order, PR bodies, draft PRs (push and PR hooks confirm)
          |
       [retro] -- retro, runbook.md, release-notes.md
          |
        [done]
```

`/kinetic:run` is the only orchestrator. It sets the phase in state before each step, reads the phase skill and follows it. No skill calls another skill and no subagent dispatches another subagent.

## Lanes and entry points

| Lane | When | Phases |
|---|---|---|
| `quick` | One small ticket, one repo, no design decisions | intake, build, review, ship, retro |
| `feature` | One repo, needs a spec | grill, spec, tickets, build, review, ship, retro |
| `epic` | Several repos | all phases; per-repo integration branches, typed edges |

The quick lane has no grill, spec or tickets phase. Its breakdown gate is a single question that also asks which seams the tests may use, because a background implementer has no one to ask.

A run starts at the first missing artifact:

| You have | The run starts at |
|---|---|
| An idea or a bare ticket | grill |
| A spec, no tickets | tickets (repo detection first) |
| A spec and tickets with edges | build |
| One small ticket, no spec | the quick lane |

A spec brought in from outside still goes through the spec gate, and tickets brought in still go through the breakdown gate. `--from build` (and `/kinetic:implement <ref>`) skips straight to build for an already specified ticket; the breakdown gate still applies.

## Approval gates

Three gates, each asked with a multiple-choice question and recorded in state (`gates`). A rejected gate sends the run back one phase with your feedback; the run never advances past an unapproved gate.

| Gate | When | What you see |
|---|---|---|
| `spec` | After the spec phase | The spec location and a three-line summary. The spec must already pass `spec_lint`. |
| `breakdown` | After tickets | Every ticket with its repo and blockers by edge type. Approving records the **grant**. |
| `ship` | After review | Per repo: integration branch, base branch, merge order, latest verify result. |

The grant is what the build agents may do without asking again: commit and push to ticket branches, make Jira transitions, open draft PRs. It never covers pushes to `main`, `master` or `Release*`, force-push after review, deploys, or production data writes. Pushes, PR creation and Jira writes are still confirmed by hooks, and a hook denial is final.

## The build loop

### Branches and worktrees

Each repo gets an **integration branch** `kinetic/<run-id>/integration`, checked out at `<run_dir>/worktrees/<repo>`. Each ticket gets its own branch `kinetic/<run-id>/<ticket-id>` and worktree `<run_dir>/worktrees/<repo>-<ticket-id>`, cut from the integration branch at dispatch time, so it already contains the work of the tickets it depends on.

### Dependency edges

Tickets block each other with exactly three edge types (in Jira, a "blocks" link plus a label `edge:snapshot`, `edge:merge` or `edge:release`):

| Edge | The downstream ticket may start when | Example |
|---|---|---|
| `snapshot` | the upstream repo has published a snapshot build and the downstream repo is pinned to it | `web` consumes a client library `api` publishes |
| `merge` | the upstream ticket is merged into its integration branch | a second ticket in the same repo builds on the first |
| `release` | the upstream version is actually released (marked by hand) | a consumer that can only use a released artifact |

`snapshot` edges need `publish_snapshot` and `pin` configured for the repos involved; without them the tickets phase uses `merge` edges instead.

### Rounds

1. `kinetic.frontier` lists the ready tickets: blockers satisfied, at most 3 running at once and at most 1 per repo.
2. Each ready ticket gets its ticket file (`<run_dir>/issues/<id>.md`), its worktree and status `running`, then all are dispatched in one message as background `implementer` agents. Each implementer follows `tdd`, runs the repo's verify command through `kinetic.verify`, and writes a report with a status: `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_DECISION` or `BLOCKED`.
3. On `DONE`, the `spec-reviewer` and `standards-reviewer` agents review the ticket's diff against the integration branch. Confirmed findings go back to a fix implementer, at most 3 fix rounds per ticket.
4. The ticket branch is merged into the integration branch (conflicts use `resolving-merge-conflicts` when available, otherwise you are asked). Downstream repos on a `snapshot` edge are pinned to the new snapshot.
5. On `NEEDS_DECISION` or `BLOCKED` you are asked, the answer is recorded as a ruling, and the same implementer resumes.

If the frontier is empty while tickets are still `todo` and nothing is running, the run is stalled on edges that will not clear by themselves. kinetic shows each waiting edge and asks whether to change its type, mark a release, or stop; it never dispatches around an edge.

Ticket statuses: `todo`, `running`, `done`, `done_with_concerns`, `needs_decision`, `blocked`, `merged`, `released`.

### Review phase

For each repo, `dev-fleet:architecture-review` and `/security-review` run when available (kinetic says which ran). Confirmed findings become fix tickets named `<repo>-review-N` that go through the same build rounds. Every changed repo is verified again; a failing verify blocks the ship gate.

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

### Related PRs:
| PR | Merge order | Relationship |

### Depends on:
- [ ] <org>/<repo>#<n>
```

Bodies are written for developers: no lists of files touched, every design decision with its reason (or flagged as unverified), evidence taken from the recorded verify runs rather than invented. Each body is re-read as a teammate who has seen neither the diff nor the tickets before it is saved. Once all PRs exist, earlier PRs are updated so their Related PRs list every sibling. No CI directive lines are added; Depends on and the merge order carry the dependency.

## Commands

| Command | What it does |
|---|---|
| `/kinetic:run <JIRA-KEY\|idea\|spec-path> [--from build]` | Orchestrates a run end to end, stopping at each gate |
| `/kinetic:implement <JIRA-KEY\|ticket-file\|spec-path>` | Alias for `run --from build` on an already specified ticket |
| `/kinetic:init [repo-path ...]` | One-time setup of repos, verify commands, snapshots, tracker; safe to re-run |
| `/kinetic:doctor` | Read-only health check with a one-line fix per failure |
| `/kinetic:status [run-dir]` | Phase, tickets, frontier and gates of a run (the active one by default) |
| `/kinetic:ask` | The lanes and the next step `next_step` computes for the active run |

## Skills and agents

| Name | Kind | Model | Role |
|---|---|---|---|
| `run` | command | sonnet | The orchestrator: lanes, gates, phases, build loop |
| `implement` | command | sonnet | `run --from build` |
| `init`, `doctor`, `status`, `ask` | commands | sonnet, haiku, haiku, haiku | Setup and read-only views |
| `grill` | phase skill | inline | Interview covering threat model and non-functional requirements; keeps the glossary and ADR drafts |
| `spec` | phase skill | inline | Spec with testing decisions, linted by `spec_lint`, published to Jira or `<run_dir>/spec.md` |
| `tickets` | phase skill | inline | Vertical slices, per-repo tickets, typed edges, validated by `graph validate` |
| `ship` | phase skill | inline | PR bodies, merge order, draft PR set |
| `retro` | phase skill | inline | Retro, runbook, release notes |
| `tdd` | skill | sonnet | Test-first loop the implementer preloads (`skills: [tdd]`) |
| `implementer` | agent | sonnet | One ticket in its own worktree; tools: Read, Edit, Write, Grep, Glob, Bash |
| `spec-reviewer` | agent | opus | Read-only: does the diff do what the ticket asks |
| `standards-reviewer` | agent | opus | Read-only: does the diff meet the repo's standards |

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
  "jira_project": "INV",
  "slice_issue_type": "Story",
  "child_issue_type": "Sub-task",
  "workspace_root": "~/workspace/kinetic-runs"
}
```

With `"tracker": "local"` the three Jira fields are null and tickets are files under `<run_dir>/issues/`.

## Where state lives

```text
<workspace_root>/<run-id>/
  state.json            run state (flock-guarded, written atomically)
  spec.md               the spec (local mode, or a copy noting the Jira key)
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

`python3 -m kinetic.state load --run <run_dir>` prints the whole state: lane, phase, tickets, slices, repos, gates, rulings, verify results and the owning session.

## What the hooks enforce

| Hook | Event | Rule |
|---|---|---|
| `completion_gate` | Stop | Blocks "done" while a repo has edits newer than its last passing verify, and names the command to run |
| `isolation` | PreToolUse on file writes | Denies writes outside the registered repos and the run directory |
| `confirm_write_ops` | PreToolUse on Bash and GitHub/Jira MCP writes | Denies `git push` to `main`, `master` or `Release*`; asks before other pushes, `gh pr` writes and Jira or GitHub write calls |
| `confirm_deploy` | PreToolUse on deploy and Tekton-trigger MCP calls | Asks first |
| `record_edit` | PostToolUse on file writes | Records edits so the Stop gate can compare them with verifies |
| `claim_run` | PostToolUse on Bash | Records the session that wrote the active-run pointer as the run's owner |
| `orient` | SessionStart | Tells a new session about the active run and the next step |

The run-scoped hooks (isolation, record_edit, completion_gate) act only in the session that owns the run and on calls whose working directory is inside the run directory, so other Claude sessions on the machine are unaffected. The push and deploy hooks always apply.

## Recovery and troubleshooting

- **Resume after a crash or in a new session.** Run `/kinetic:run` again. It finds the active run, rewrites the pointer (which claims the run for the new session), and resumes at the recorded phase. Recorded gates stay approved. For a ticket still `running` with no report, kinetic shows what its worktree holds and asks whether to re-dispatch an implementer there or set it back to `todo`.
- **A crash during a fix round.** Recovery cannot yet tell a dead fix agent from a finished first round; check `<run_dir>/reports/<id>-fix-N.md` by hand.
- **Abandon a run.** `rm -f ~/.config/kinetic/active-run`. The run directory stays for reference.
- **A hook denied something.** A denial is final for that action. Read the reason: an isolation denial names the allowed roots; a push denial means the target is a protected branch.
- **`/kinetic:init` is denied writing config.** You are in the session that owns the active run; run it from another session.
- **The run is stalled.** The frontier is empty with tickets still `todo`. kinetic shows the waiting edges; usually a `snapshot` edge between repos without `publish_snapshot`/`pin`, or a `release` edge nobody has marked. Mark a release with `python3 -m kinetic.state set-ticket --run <run_dir> --id <upstream-id> --field status=released`.
- **Doctor checks:** `git` and `gh` on PATH, `gh auth status`, a readable `repos.json`, a resolvable verify command per repo, the optional companion skills and plugins, and a reminder to check the Atlassian MCP with `/mcp`.

Run scripts directly with `PYTHONPATH=<kinetic>/scripts python3 -m kinetic.<module> ...`.

## Code layout

```text
.claude-plugin/plugin.json   plugin manifest
skills/<name>/SKILL.md       commands and phase skills; skills/run/guides/ holds the
                             build loop, lanes, gates and recovery guides
agents/                      implementer, spec-reviewer, standards-reviewer
hooks/                       hooks.json and one Python script per hook; _common.py
                             resolves the active run and its session scope
scripts/kinetic/             the deterministic core
tests/                       unittest suite, including a two-repo end-to-end fixture
docs/                        comparison, design spec, implementation plan, rulings
```

| Module | Responsibility |
|---|---|
| `state.py` | Run state: init, phase, slices, tickets, repos, gates, rulings, verify and edit stamps, owner session; flock-guarded atomic writes; CLI |
| `graph.py` | Validates the ticket graph (missing repo, edge types, unknown blockers, unused slices, cycles) and gives a topological order |
| `frontier.py` | Ready tickets: satisfied blockers, the cap of 3 running, one per repo |
| `gitops.py` | `worktree`, `merge` (ticket into integration), `merge-order` across repos, `pin` downstream repos to a snapshot |
| `verify.py` | Runs a repo's verify command, logs it and records the result in state |
| `config.py` | Resolves a repo's config from `repos.json` and `.kinetic.json` |
| `detect_repos.py` | Proposes a verify command from build markers (Maven, Gradle, npm, Go, Cargo, pyproject, Makefile) |
| `doctor.py` | The health checks behind `/kinetic:doctor` |
| `spec_lint.py` | Checks a spec has non-empty Threat model, Non-functional requirements and Acceptance criteria sections |
| `status.py` | Renders `/kinetic:status` |
| `next_step.py` | Computes the next step for `/kinetic:ask` and the SessionStart hook |

## Tests

```
PYTHONPATH=scripts python3 -m unittest discover -s tests -v
```

The suite covers every script module and every hook, plus an end-to-end test that drives the scripts through a two-repo run with real git repositories and a `merge` edge.

## Status and known limitations

kinetic is at v0 (see `.claude-plugin/plugin.json` for the version). The scripts and hooks are tested; the skills and agents have not yet been exercised in a live end-to-end run. `docs/plan/kinetic-v0-rulings.md` records every decision made while building it and the v0.2 backlog.

Not yet verified in a live session:

- that `${CLAUDE_PLUGIN_ROOT}` expands where the skills use it;
- that `skills: [tdd]` resolves to kinetic's own `tdd` skill;
- whether subagent hook payloads carry the parent session id (the cwd rule covers implementers either way).

Known limitations:

- A bare `git push` on a protected branch only asks; it is not denied.
- `gh api` calls (including merges) pass the write-ops hook, and base branches other than `main`, `master` and `Release*` are not protected.
- Isolation cannot tell implementers apart within the run directory.
- Until a session claims the run, or when a hook payload has no session id, the run-scoped hooks act on every session.
- No skill evals yet; `/kinetic:status` shows no PR health or Jira transitions.

## License

Some skills are adapted from third-party work (Matt Pocock's skills, MIT); see `THIRD_PARTY_LICENSES.md`.
