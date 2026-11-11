# kinetic: SDLC pipeline plugin, design spec

Status: draft for review. Design only; nothing is implemented.
Inputs: [../sdlc-plugin-comparison.md](../sdlc-plugin-comparison.md); Pocock skills (`mattpocock/skills`), superpowers 7.0.0, dev-fleet, devflow 1.3.3 (decisioning team).

## 1. Problem and goal

The three plugins each cover part of the SDLC and none covers all of it (see the comparison). kinetic is one pipeline that takes an idea, spec or ticket to a set of linked PRs, keeping:

- Pocock: grilling with glossary/ADRs, spec, tracer-bullet tickets with blocking edges, `tdd`, two-axis review, retro.
- superpowers: evidence-before-claims, careful handling of review feedback, thin orchestration with a decision ledger.
- dev-fleet: hook-enforced safety, multi-repo coordination, architecture review, release.

and filling the gaps: threat model and NFRs at design time, completion gate as enforcement, stack-agnostic verification, docs deliverables (runbook, release notes), typed cross-repo edges.

Decisions already made with the user:

| Decision | Choice |
|---|---|
| Platform | Unix-only (macOS, Linux) |
| Location | Standalone repo in `~/workspace/lab/kinetic` |
| Composition | Hybrid: copy and adapt Pocock skills; call superpowers and dev-fleet skills by name |
| Multi-repo | Extend Pocock's task-graph model (tracker as state, frontier dispatch), not dev-fleet agents |
| Tracker | Jira, with local-file fallback |
| Autonomy | Gates at decisions |
| Stack | Stack-agnostic: each repo declares its own commands |
| Repo config | Central `~/.config/kinetic/repos.json`, overridden by a repo-root `.kinetic.json` |
| Existing overlap | devflow already covers much of this; user chose to build kinetic as designed anyway |

## 2. Lanes

| Lane | When | Phases |
|---|---|---|
| quick | One small ticket, one repo, no design decisions | implement, verify, review, ship |
| feature | One repo, needs a spec | grill, spec, tickets, build, review, ship, retro |
| epic | Several repos | all phases, with repo detection, typed edges, per-repo integration branches |

The lane is picked at intake by the LLM (size and uncertainty are judgment calls) using the repo count from `detect_repos.py`.

## 3. Entry points

- `/kinetic:run <JIRA-KEY | idea | spec path>`: starts at the first phase whose artifact is missing.
- `/kinetic:implement <ref>`: alias for `run --from build`. Refuses, pointing at `run`, if the ticket has no acceptance criteria or no repo.
- `/kinetic:init`: interactive setup (tools, auth, tracker, repo roots, writes config). Safe to re-run.
- `/kinetic:doctor`: read-only check; reports missing reused skills, unreachable tracker, absent verify commands.
- `/kinetic:status`: renders run state, frontier and PR health.
- `/kinetic:ask`: router, prints the lanes and what to run now (see 7).

| What the user has | `run` starts at |
|---|---|
| Idea or bare ticket | grill |
| Spec, no tickets | tickets (repo detection first) |
| Spec and tickets with edges | build (frontier) |
| One small ticket, no spec | quick lane |

## 4. Components

### Commands (orchestrate; skills and subagents execute)

| Name | Model | Role |
|---|---|---|
| `/kinetic:run` | sonnet | Lane pick, approval gates, build loop. Thin orchestrator: dispatches, tracks, relays; does not read diffs. Phase guides live under `run/` |
| `/kinetic:implement` | sonnet | Alias of `run --from build` |
| `/kinetic:init` | sonnet | Interview over `detect_repos.py` output |
| `/kinetic:doctor` | haiku | Wraps `doctor.py` |
| `/kinetic:status` | haiku | Wraps `status.py` |
| `/kinetic:ask` | haiku | Router over `next_step.py` |

### Skills (no skill calls another skill)

| Name | Model | Source | Role |
|---|---|---|---|
| `grill` | sonnet | MODIFY Pocock `grill-with-docs`/`grilling` | Interview; maintains `GLOSSARY.md` and ADRs; covers threat model and NFRs |
| `spec` | sonnet | MODIFY Pocock `to-spec` | Writes the spec, runs `spec_lint.py`, publishes to Jira or local files |
| `tickets` | inherits (inline) | MODIFY Pocock `to-tickets` | Slice parents, per-repo child tickets, edge-type labels; runs `graph.py` |
| `tdd` | inherits | REUSE (copy) Pocock `tdd` incl. `tests.md`, `mocking.md` | Preloaded into `implementer` |
| `ship` | sonnet | MODIFY Pocock `pr` | PR bodies, merge order, draft PR set via `gh` |
| `retro` | sonnet | MODIFY Pocock `retro` | Retro plus runbook and release-notes drafts |

### Subagents (isolated context, dispatched only from `run`)

| Name | Model | Role |
|---|---|---|
| `implementer` | sonnet | One ticket, own worktree, background. Runs `tdd` then `verify.py`. Writes a report file |
| `standards-reviewer` | opus | Does the diff follow the repo's documented standards |
| `spec-reviewer` | opus | Does the diff match the ticket and spec |

Report contract (borrowed from devflow): status is one of DONE, DONE_WITH_CONCERNS, NEEDS_DECISION, BLOCKED; the report is a pointer-only file (ticket id, branch, verify result path, open questions).

### Scripts (deterministic; never call an LLM)

`state.py`, `graph.py`, `frontier.py`, `verify.py`, `pin.py`, `merge.py`, `merge_order.py`, `spec_lint.py`, `detect_repos.py`, `doctor.py`, `status.py`, `next_step.py`, plus the hook scripts. Python 3, stdlib only where possible; each has unit tests.

### Hooks

| Event | Script | Behaviour |
|---|---|---|
| PreToolUse Write/Edit | workspace isolation (ported from dev-fleet) | Deny writes outside the ticket's worktree |
| PreToolUse Bash and MCP write tools | confirm write ops (ported) | Confirm push, `gh pr`, Jira writes, PR merge |
| PreToolUse deploy tools | confirm deploy (ported) | Confirm deploy and build triggers |
| Stop | completion gate (new) | Block a "done" claim when state has no passing verify result recorded after the last edit |
| SessionStart | orient (new) | Inject a short pointer to the active run, phase and next command; silent when no run exists |

Ported hooks need retargeting from dev-fleet's folder model to kinetic's run state.

### Reused by name (compose)

`find-ticket-repos`, `checkout-ticket-repos`, `resolving-merge-conflicts` (user skills, not packaged; `doctor` reports absence, plugin needs a fallback or copies); `superpowers:receiving-code-review`; `dev-fleet:architecture-review` (accepts a repo path, verified); `/security-review`; `dev-fleet:release` (optional, Upgrade k8s repos only; whether it needs a dev-fleet project is unverified).

## 5. Flow (epic lane)

```
/kinetic:run <ref>
 -> doctor.py -> state.py init -> lane pick
 -> grill -> spec --(spec_lint.py)--> GATE: approve spec
 -> find-ticket-repos -> tickets --(graph.py)--> GATE: approve breakdown (records the single grant)
 -> worktrees per repo, integration branch per repo
 -> BUILD LOOP
      frontier.py -> [implementer || implementer || implementer]   <=3 concurrent
        each: tdd -> verify.py -> report
      per finished ticket: [standards-reviewer || spec-reviewer]
        -> receiving-code-review -> fix via new implementer if needed
        -> merge.py into the repo's integration branch (conflict -> resolving-merge-conflicts)
        -> pin.py for downstream repos when the edge is snapshot-typed
        -> state.py update -> frontier.py   (until frontier empty)
 -> architecture-review + security-review on every integration branch (<=3 rounds)
 -> ship: merge_order.py -> GATE: push/PR (hook) -> draft PR set
 -> optional dev-fleet:release -> GATE: deploy (hook)
 -> retro
```

Feature lane: same with one repo, no repo detection. Quick lane: one implementer, review, ship.

## 6. Data model

- `state.json` under `<workspace>/<run-id>/`: only shared state. Scripts write it; the LLM reads fields, never parses raw output. Holds lane, phase, tickets and statuses, gate approvals, rulings, verify results.
- Tickets: Jira issues with native "blocks" links; edge type in a label (`edge:snapshot`, `edge:merge`, `edge:release`). Local mode: one file per ticket with the edge type inline.
- Slice model: a vertical slice is a parent ticket; each repo's share is a child ticket (the unit an agent implements). The slice stays the unit you demo and verify.
- Edge semantics: `snapshot` = downstream may start once upstream has a snapshot build and is pinned; `merge` = downstream waits for upstream merge; `release` = waits for a released version.
- Repo config: `verify`, `publish_snapshot`, `pin`, `base_branch` per repo; central file, repo-root override wins.
- Grant: approving the breakdown records one grant (commits and pushes to the ticket branch, Jira transitions, opening draft PRs). Never master or Release pushes, force-push after review, deploys without the deploy hook's confirmation, or prod data writes.

## 7. Router and orientation

`/kinetic:ask` prints the lanes and the pipeline map and, from `next_step.py`, the current run's next command and why (for example "frontier has 2 ready tickets: run `/kinetic:run`"). Suggestions come from the script, never from prose, so they cannot go stale. The SessionStart hook injects a few lines only. It deliberately does not copy superpowers' "invoke a skill at 1% chance" mandate; enforcement lives in hooks.

## 8. Non-functional

- Platform: Unix-only; bash and Python 3 hooks; no Windows paths.
- Concurrency: at most 3 implementers at once by default; one implementer per repo at a time (same-repo tasks serialize on the repo's integration branch).
- Cost: opus only for the two reviewers (plus architecture-review as shipped); everything else sonnet or haiku.
- Safety: hooks enforce isolation and confirmations; the completion gate enforces evidence before "done".
- Recovery: never assume an agent from a previous session is alive; re-derive from `state.json`, reports and git.

## 9. Execution strategy

| Wave | Tasks | Mode |
|---|---|---|
| 1 | (a) scripts and unit tests; (b) hooks ported from dev-fleet; (c) copy and adapt the six Pocock skills | parallel, sonnet |
| 2 | three subagents, built against wave 1 script contracts | sequential after 1a |
| 3 | `run`, `implement`, `init`, `doctor`, `status`, `ask`, SessionStart hook | sequential after 1 and 2 |
| 4 | Skill Forge quality gate on every new or modified skill and subagent; end-to-end dry run in local-tracker mode on a two-repo fixture | last |

Dispatching wave 1 as parallel subagents needs the user's approval at implementation time.

## 10. Open items and risks

1. Pocock license: resolved. `mattpocock/skills` is MIT (confirmed by the user 2026-11-11); copies keep the notice in `THIRD_PARTY_LICENSES.md`.
2. `dev-fleet:release`: unknown whether it needs a dev-fleet project; may need a standalone path or be dropped.
3. `find-ticket-repos`, `checkout-ticket-repos`, `resolving-merge-conflicts` are unpackaged user skills; need fallbacks or copies.
4. Overlap with devflow (`teams/decisioning/plugins/devflow`): publishing kinetic into llm-context would hit BugBot's duplicate-skill rule (blocking). Mitigation: keep standalone, or differentiate scope explicitly in the PR.
5. Ported dev-fleet hooks assume dev-fleet's folder model; retargeting is real work.
6. Router conflict: if superpowers or `ask-matt` are also loaded, three routers compete; the kinetic hook stays silent unless a run exists.
7. Edge typing and the slice-parent model are new design, untested; validate in the wave 4 dry run.
8. Not verified: devflow's behaviour beyond the README, `plan.md` and `build.md`; superpowers hook contents; dev-fleet hook deny logic.
