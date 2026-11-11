# SDLC comparison: Matt Pocock skills, superpowers, dev-fleet

Sources read: Pocock skills in `~/.agents/skills` (symlinked into `~/.claude/skills`), superpowers 7.0.0 (plugin cache), dev-fleet (`teams/investor/plugins/dev-fleet`).

## What each one is

| | Pocock skills | superpowers 7.0.0 | dev-fleet |
|---|---|---|---|
| Shape | About 33 skills in `~/.agents/skills`. No plugin manifest. | 15 skills, a SessionStart hook and a bootstrap skill (`using-superpowers`). | About 45 skills, the `parallel-worker` agent, 18+ hooks, templates, a project and portfolio model. Upgrade-internal. |
| Core idea | One main flow from idea to ship, run by a human who keeps taste and decisions. | An agent that follows a fixed discipline: brainstorm, plan, test-first, review, verify. | A fleet of isolated agents, with the DAG, hooks and file state doing the coordinating. |
| Unit of work | One idea, spec or ticket per context window. | One feature per session, split into plan tasks. | One epic across several repos, one agent per repo and branch. |
| Where discipline lives | In the human's habits and the skill text. | In the skill text. Heavy tone ("MUST", "Iron Law"). | In hooks and scripts that deny or confirm actions, plus skill prose. |

## Coverage by SDLC phase

| Phase | Pocock | superpowers | dev-fleet |
|---|---|---|---|
| Requirements and discovery | Strong. `grill-with-docs` writes `GLOSSARY.md` and ADRs as it goes. `research`, `to-questionnaire`, `wayfinder` cover unclear or very large work. | Good. `brainstorming` elicits intent and ends in a design doc. Conversational, no durable glossary. | Weak in the skills read. `recon:scout` (pre-design mapping) and `define-agents` (epic to agents), but it starts from an existing ticket. |
| Design | `codebase-design`, `improve-codebase-architecture`, `prototype`. | Folded into brainstorming. No architecture vocabulary or prototype step. | Delegated to investor-workflow (design and HLD reviewers). `architecture-review` runs later, on the diff. |
| Planning and decomposition | Strongest. `to-spec` then `to-tickets` give tracer-bullet tickets with blocking edges. `wayfinder` for work larger than one session. | `writing-plans`: bite-sized tasks with files, names and tests, saved to `docs/superpowers/plans/`. | `define-agents` decomposes by repo, builds a DAG in `dependencies.json`, can run N competing decompositions and pick one. |
| Implementation | `implement`, then `tdd` (vertical slices, tests only at agreed seams), then `code-review`. | `executing-plans`, or `subagent-driven-development`: fresh agent per task, spec and quality review per task, final whole-branch review. | `implement`, with optional `--fanout N` (N attempts in worktrees, objectively gated, best selected). |
| Testing | `tdd` is the best read: names tautological and implementation-coupled tests as anti-patterns. | `test-driven-development`, `verification-before-completion` (no completion claims without fresh evidence). | `run-checks`: tool-enforced build, tests, jacoco coverage, checkstyle, Java version. `bump-client-version`. |
| Review | `code-review`: Standards and Spec axes in parallel. `/pr` shapes the PR body. | Request and receive review. `receiving-code-review` requires verifying feedback. | Broadest. `review` (code, security, architecture, spec lenses), `architecture-review` (outbox, Kafka idempotency, sagas, money), `review-pr`, `address-review`. |
| Integration and delivery | Almost nothing beyond `/pr` and `resolving-merge-conflicts`. | `finishing-a-development-branch`: tests, then merge, PR or discard, then worktree cleanup. | `push`, `open-pr` (draft, with cross-PR dependency directives), `rebase`, `release` (k8s-template deploy request from merged PRs, tracked), `sideload`. |
| Operations and feedback | `triage` for inbound issues. `retro` improves the agent's environment. | `diagnosing-superpowers` analyses a bad session. Nothing for production. | `status`, `portfolio-*`, `ticket-map`, `reflect`, `feedback`. No production monitoring. |
| Debugging | `diagnosing-bugs`: no theorising until a one-command red feedback loop exists. | `systematic-debugging`. | No dedicated skill. Relies on companion plugins (tekton, observability). |

## Strengths

**Pocock**
- Best at requirements and decomposition. Tickets carry blocking edges and could feed dev-fleet or a tracker.
- Handles uncertainty explicitly: `wayfinder`, `prototype`, `research`.
- `GLOSSARY.md` and ADR habit gives later agents shared vocabulary.
- Context hygiene is a stated discipline (smart zone, five-option phase-boundary rule).
- `retro` targets the agent's environment, unique across the three.

**superpowers**
- Most rigorous per-task loop: fresh subagent per task, two-part review per task, final branch review.
- Strongest anti-hallucination rule and most careful handling of review feedback.
- Portable and low setup cost. Needs no tracker or repo layout.
- `subagent-driven-development` runs without pausing and records decisions as "Ruling" entries in a ledger.

**dev-fleet**
- Only one with enforcement: hooks block writes outside the workspace and require confirmation before push, Jira writes, PR merge and deploy; a VPN check gates Bash.
- Only one with real multi-repo coordination: DAG, READY or BLOCKED, rebases onto dependency branches, peer messaging via `OUTBOX.md`.
- Covers release tracking and deploy confirmation.
- Grounded in Upgrade's stack (Maven, checkstyle, Testcontainers, Artifactory, k8s-template, Minions bot).
- Self-observing: usage telemetry feeds `reflect`; `fleet-doctor` pre-flight.

## Weaknesses

**Pocock**
- No enforcement; several skills are `disable-model-invocation`, so the human must remember to run them.
- Single-agent, single-repo by design.
- Needs per-repo setup (`setup-matt-pocock-skills`).
- Thin on delivery and operations; review has no domain lens (distributed systems, money, security).
- Coupled to an issue-tracker abstraction; mapping to Jira is the user's job.

**superpowers**
- Prose-only enforcement; the one hook is SessionStart. Compliance depends on persuasive, token-heavy wording.
- Single-repo, single-session; isolation is a worktree only.
- No durable requirements artifacts, glossary, ADRs or tracker integration. Default plan path conflicts with the user's own storage rule.
- Nothing after merge.
- "Never stop to ask" mode substitutes agent rulings for human decisions on ambiguous plans.

**dev-fleet**
- Heaviest: README 71KB, CHANGELOG 447KB; needs VPN, Artifactory, sdkman, gh SSH, Docker. Much of it is overhead for single-repo work.
- Upgrade-specific and Java/Maven-centric; not portable.
- Weakest before implementation: no grilling, glossary or ADR habit.
- Thin test philosophy: `run-checks` enforces pass and coverage, but no TDD skill was seen.
- Several lenses depend on optional plugins (`pr-review-toolkit`, `investor-workflow`), with a documented MDM-allowlist failure mode.
- Clone-based isolation is state-heavy (clones, `CONTEXT.md`, `OUTBOX.md`, schema migrations).

## Gaps

**In all three**
- Security and threat modelling as a design-phase activity.
- Non-functional requirements (performance, capacity, SLOs) as a planning input.
- Production feedback closing the loop into requirements.
- Application data and schema migration planning.
- Documentation as a deliverable (runbooks, API docs, release notes).
- Estimation and capacity planning.

**By plugin**
- Pocock: enforcement, multi-repo orchestration, delivery, release.
- superpowers: durable requirements artifacts, multi-repo support, anything after merge, tracker integration.
- dev-fleet: discovery and elicitation, a testing philosophy, a lightweight mode.

## How they fit together

| SDLC stage | Best of the three |
|---|---|
| Discovery and decomposition | Pocock (`grill-with-docs`, `to-spec`, `to-tickets`, `wayfinder`) |
| Test discipline | Pocock `tdd`, plus superpowers `verification-before-completion` |
| Per-task execution and review loop | superpowers `subagent-driven-development` |
| Multi-repo orchestration and enforcement | dev-fleet |
| Review depth | dev-fleet `review` and `architecture-review` |
| Release | dev-fleet `release` |

Overlap: `to-tickets` vs `define-agents`, `implement` in all three, the review skills. The three split work differently (Pocock by vertical slice, superpowers by task, dev-fleet by repo); running them together means picking one decomposition. superpowers' "invoke at 1% chance" bootstrap and Pocock's "read the SKILL.md first" router both compete for control of the process and will conflict.

## Not verified

- dev-fleet's plugin version and the superpowers hook script contents.
- Skill bodies for `wayfinder`, `triage`, `release`, `architecture-review`, `recon:scout` (judged from frontmatter, READMEs and the router).
- Whether `~/.agents/skills` is a full upstream copy or a subset, and whether it has hooks.
- dev-fleet enforcement is judged from `hooks.json` entries, not each script's deny logic.
