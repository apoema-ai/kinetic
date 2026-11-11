# Kinetic: pluggable trackers, human-ready tickets, relationship types, PR template

Status: draft for approval. Base: kinetic 0.2.0 (`05bb9fb`). Builds on [kinetic-sdlc-pipeline-design.md](kinetic-sdlc-pipeline-design.md).

## Why

Kinetic assumes every ticket is agent work and that the tracker is Jira or a local folder. Real runs mix in steps only a person can do (Terraform apply, secrets, k8s-template, prod config, a decision nobody has made), and today the only way to make a ticket wait on such a step is the hand-marked `release` edge. Teams also track work in GitHub, Linear or Jira with their own label names, and want their own PR body layout.

## Goals

1. **Human-ready tickets.** A ticket is `agent` or `human`. Human tickets are never dispatched; the run keeps going around them and shows them as "waiting on you".
2. **Tracker choice.** Jira, GitHub, Linear and local markdown as equal choices, plus "other" described in prose. Label, status and link names map onto what the team already uses.
3. **Relationship types.** Besides `blocks` (with its existing `snapshot` / `merge` / `release` edge types): soft precedence, ships together, related.
4. **PR body template.** A tracker-agnostic version of the current layout ships as the default; the user can point to their own template.

## Non-goals

- Reading state back from Jira, GitHub or Linear. Kinetic state stays authoritative; remote trackers are a mirror. (Local markdown is the one exception, below.)
- Different trackers for different repos in one run.
- A triage skill or triage queue (Pocock's `triage`); only the agent/human split is borrowed.
- GitLab (not asked for; the "other" adapter covers it in prose).
- Proof that a human ticket was done. The user's word is enough.

## Anti-goals

- Any Python that talks to a tracker. Adding a tracker must add no code, only an adapter file.
- Local mode turning into a binary or database store. It stays markdown a person can read.
- A human ticket that silently stalls the run, or a run that looks stuck when only human work is left.

## Decided by the user

- Human-ready = any task that needs to be performed by a human.
- Behavior when the frontier reaches a human ticket, as proposed and confirmed: the run continues with independent agent tickets; the human ticket shows as waiting on you with its checklist, what it blocks, and its tracker link; it is assigned to the user in the tracker; the user marks it done in chat or by command; it is recorded as done by a human, with no verify gate; when only human tickets are left the run pauses and says so.
- The tickets skill proposes agent or human per ticket and the user confirms at the breakdown gate. An implementer can hand a step back as needing a human.
- Trackers: Jira, local, GitHub, Linear. Local means markdown a human can read.
- PR body: the agnostic version of the open-multi-repo-prs layout is the default; the user can set their own template.
- Relationships: keep blocks; add soft precedence, ships together, related.

## Design

### 1. Ticket model (`state.py`, `graph.py`)

New ticket fields, all optional, with defaults that keep 0.2.0 runs valid:

| Field | Values | Default | Meaning |
|---|---|---|---|
| `kind` | `agent`, `human` | `agent` | Who does it. |
| `after` | list of ticket ids | `[]` | Soft precedence: prefer those first, never wait on them. |
| `ships_with` | group name | `null` | Tickets in the same group merge and release as a set. |
| `related` | list of ticket ids | `[]` | Context only; no ordering. |
| `human_note` | text | `null` | Optional link or note the user gives when marking a human ticket done. |

`blocked_by` is unchanged.

Rules:

- **Human done.** A new CLI, `state.py human-done --run <dir> --id <id> [--note <text>]`, sets `status=done`, `done_by=human` and `human_note`. `done_refusal` skips tickets with `kind=human`. `set-ticket --field status=done` on a human ticket is refused with a pointer to `human-done`, so the verify gate cannot be bypassed on agent tickets by mislabeling.
- **Edges onto a human blocker.** An edge whose blocker has `kind=human` is satisfied once the blocker is `done`, whatever its edge type. Human work has no merge or release of its own.
- **`graph.py validate`.** It gains these checks:
  - errors: an unknown id in `after` or `related`; an `after` that contradicts a `blocks` path (A after B while B is blocked by A); a `ships_with` group of one ticket; a human ticket with no acceptance criteria or checklist (checked by the tickets skill, not the script).
  - warnings: an `after` cycle among soft edges only (ignored for ordering).
- **`graph.py topo`** orders by `blocked_by`, then uses `after` to break ties.

### 2. Frontier (`frontier.py`)

Output becomes `{"ready": [...], "waiting_on_you": [...], "only_human_left": bool}`.

- **`ready`.** Unchanged rules (cap 3, one per repo, edges satisfied), but human tickets are excluded. Among ready tickets, one whose `after` targets are all done or not ready comes before one that still has an `after` target ready. Soft precedence only reorders the list; it never removes a ticket.
- **`waiting_on_you`.** Human tickets that are `todo` with all their `blocked_by` satisfied.
- **`only_human_left`.** True when nothing is ready or occupying a repo, and every remaining `todo` ticket is human or blocked behind a human ticket.

Human tickets need no repo. `repo` stays optional for them, so the one-per-repo rule does not apply.

### 3. Orchestrator (`run/SKILL.md`, `guides/build-loop.md`)

- **Each round.** Print `waiting_on_you` with each ticket's checklist, the tickets blocked behind it, and its tracker link.
- **When `only_human_left` is true.** Stop the round with "Only human tickets are left: <list>. Tell me when one is done." Do not treat it as the stalled case.
- **"Done with <id>" from the user, with an optional note or link.** Run `human-done`, mirror it to the tracker, re-run the frontier.
- **New implementer status `NEEDS_HUMAN`.** The report names the manual step and why. The orchestrator then:
  1. creates a human ticket for that step, with the reported step as its checklist;
  2. adds it to the original ticket's `blocked_by`;
  3. sets the original ticket back to `todo`, keeping its worktree and branch;
  4. shows the new ticket to the user.

  On re-dispatch the implementer gets the same worktree. The implementer brief and report contract in `agents/implementer.md` gain this status.
- **The existing `release` edge stays as it is.** Modelling releases as human tickets is possible but not required; existing runs keep working.

### 4. Tickets phase (`tickets/SKILL.md`)

- Each child ticket gets `Type: agent | human`. The skill proposes it and gives a reason in the breakdown table; the breakdown gate shows the human ones first.
- The skill adds `After:`, `Ships with:` and `Related:` lines where they apply, and passes them to `set-ticket`.
- Human tickets are written as a checklist of manual steps with the expected outcome. They have no Interfaces section.

### 5. Tracker adapters

A tracker is one markdown file per tracker in `trackers/` in the plugin:

```text
trackers/jira.md  trackers/github.md  trackers/linear.md  trackers/local.md  trackers/other.md
```

Each file has two parts.

**Operations**, as prose instructions the skills follow:

- create a slice parent;
- create a child under a parent;
- link a blocker (with its edge type);
- link soft precedence, ships-with and related;
- set the kind;
- move a status;
- assign to the user;
- fetch a ticket;
- comment;
- a ticket URL or short reference for PR bodies.

**Default names**, a fenced `json` block mapping kinetic roles to tracker names:

```json
{
  "kind": {"agent": "kind:agent", "human": "kind:human"},
  "edge": {"snapshot": "edge:snapshot", "merge": "edge:merge", "release": "edge:release"},
  "after": "after", "ships_with": "ships-with:<group>", "related": "relates to",
  "status": {"todo": "To Do", "running": "In Progress", "done": "Done", "merged": "Done", "blocked": "Blocked"}
}
```

Defaults per tracker:

| Tracker | Access | Hierarchy | Blocks | Soft precedence | Ships together | Related | Kind |
|---|---|---|---|---|---|---|---|
| Jira | Atlassian MCP | parent and child issues | native "blocks" link, plus an edge label | label `after:<key>` | label `ships-with:<group>` | native "relates to" | label |
| GitHub | `gh` CLI | sub-issues | native "blocked by" relationship, plus an edge label | `After: #n` line in the body | label | `Related: #n` line in the body | label |
| Linear | Linear MCP | sub-issues | native "blocks" relation, plus an edge label | label | label | native "related" relation | label |
| Local | files | slice folder and ticket files | `Blocked by:` line | `After:` line | `Ships with:` line | `Related:` line | `Type:` line |
| Other | the user's prose | as described | as described | as described | as described | as described | as described |

The builder must confirm each native relationship against the tool actually available: the `gh` version and its sub-issue and dependency support, and the Linear MCP's tool list. Where a native relationship is missing, the adapter falls back to a label or a body line, and says so.

**Configuration** lives in `~/.config/kinetic/settings.json`; a repo's `.kinetic.json` cannot change the tracker:

```json
{
  "tracker": "jira | github | linear | local | other",
  "tracker_settings": {"jira_project": "INV", "slice_issue_type": "Epic", "child_issue_type": "Story",
                       "github_repo": "org/repo", "linear_team": "ENG"},
  "tracker_names": {"kind": {"human": "needs-ops"}},
  "tracker_description": "prose, for tracker=other only",
  "pr_template": "/abs/path/to/template.md"
}
```

- `tracker_names` is deep-merged over the adapter's defaults.
- The existing `jira_project`, `slice_issue_type` and `child_issue_type` keys are still read, so 0.2.0 configs keep working.
- GitHub needs `github_repo`, the one repo that holds the run's issues, because a run spans several repos.

**A new script, `scripts/kinetic/tracker.py`.** It does no tracker I/O. It resolves the settings and prints a JSON blob: the tracker, the adapter path and the merged names. Its main job is that the merge rule and the validation are unit-tested, not left to prose. Validation covers an unknown tracker, missing required settings for the chosen tracker, and `other` without a description.

**Skills read the adapter, never hardcode a tracker.** These skills change:

- tickets, spec and implement: their Jira-only branches go;
- the `implementer` brief: `Jira key:` becomes `Ticket ref:` plus the adapter path;
- ship: it uses the adapter's ticket references;
- init and doctor (below).

### 6. Local tracker as readable markdown

- Ticket files stay at `<run_dir>/issues/NN-<repo>-<slug>.md`, as today. Their header lines are, in this order:
  - `Status:`
  - `Type:`
  - `Blocked by: 01 (merge), 02 (snapshot)`
  - `After:`
  - `Ships with:`
  - `Related:`
  - `Assignee:`
  - `Labels:`
- **A new script, `scripts/kinetic/board.py`.**
  - `board.py render --run <dir>` writes `<run_dir>/issues/README.md`. It is one table, with waiting-on-you human tickets first, then the rest in topo order. The columns are id, title, type, status, blocked by and after.
  - `board.py header --run <dir> --id <id>` rewrites one ticket file's header lines from state.
  - The orchestrator runs both after every state change in local mode.
- **Drift.** `board.py drift --run <dir>` compares the header lines of each ticket file with state and prints the differences as JSON. At the start of each round the orchestrator runs it. If anything differs, it shows the differences and asks whether to apply each one through `set-ticket` / `human-done` or to overwrite the file. State is never changed without that answer. A user marking a human ticket done by editing `Status: done` in its file goes through the same path.

### 7. PR body template (`ship`)

- The layout in `ship/SKILL.md` ("PR body layout") moves to `templates/pr-body.md` unchanged in substance. The writing rules stay in the skill.
- **Placeholders**, which the ship skill fills:

  | Placeholder | What it holds |
  |---|---|
  | `<<TICKETS>>` | One line per ticket, as `<adapter ref> - <title>`, linked. |
  | `<<TITLE_KEY>>` | The slice reference from the adapter, or the run id. |
  | `<<DESCRIPTION>>` | The description section. |
  | `<<DESIGN_DECISIONS>>` | The design decisions section. |
  | `<<ARCHITECTURE>>` | The architecture section. |
  | `<<ATTENTION_POINTS>>` | The attention points section. |
  | `<<MANUAL_STEPS>>` | New. Each human ticket this repo's tickets depend on or relate to, with done-by-human and the note or link. |
  | `<<RELATED_PRS>>` | Related PRs, as today. |
  | `<<DEPENDS_ON>>` | Depends-on PRs, as today. |
  | `<<SHIPS_WITH>>` | New. The PRs that must merge together with this one. |

  The prose sections (Description, Design decisions, Architecture, Attention points) are written by the model. The other placeholders are data the skill fills.
- **Template resolution.** The ship skill uses the first of:
  1. `pr_template` in the repo's `.kinetic.json`;
  2. `pr_template` in `settings.json`;
  3. `templates/pr-body.md`.

  A missing file is an error, not a silent fallback. A user template's unknown `<<NAME>>` placeholders are left as is and listed in the ship report. A section whose placeholder fills empty is dropped, as today.
- **The repo's `.github/pull_request_template.md`** is still merged after Description, as today.
- **Open human tickets.** A human ticket this repo depends on that is still not done when ship runs goes into the attention points' `[!WARNING]` alert as a merge blocker. Ship still opens the drafts. This was the designer's call.
- **Ships together.** For a `ships_with` group across repos, every PR in the group gets the alert line "Merge together with: ..." in its attention points, and the merge order puts the group adjacent.

### 8. Init, doctor, status

- **Init** asks, one question at a time:
  1. the tracker, recommending Jira if Atlassian MCP is connected, or GitHub if the repos are on GitHub;
  2. that tracker's required settings;
  3. "keep the default names?" (recommended yes); on no, it collects overrides for kind, edges and statuses;
  4. "use the default PR template?" (recommended yes); on no, the template's path.

  It writes `settings.json`, then runs doctor.
- **Doctor** checks, read-only:
  - the adapter for the configured tracker exists;
  - its access tool is reachable: Atlassian MCP, `gh auth status`, or the Linear MCP tools;
  - the settings are valid (`tracker.py`);
  - `pr_template`, if set, exists;
  - the configured labels exist in the tracker.

  Doctor does not create labels. Init offers to create missing ones, asking first, since that is a tracker write.
- **Status** shows a "Waiting on you" block above the ticket table.

## Compatibility

- **0.2.0 state files.** A missing new field takes its default (`kind=agent`, empty lists, null). No migration script.
- **0.2.0 settings.** The Jira-only keys are still read, and `tracker: jira|local` keeps its meaning.
- **Version.** This becomes 0.3.0.

## Testing

- **Unit tests**, test-first, one per new rule:
  - `state.py`: `human-done`, the refusal of `set-ticket status=done` on a human ticket, the defaults.
  - `graph.py`: the new validations, and topo with soft edges.
  - `frontier.py`: human exclusion, `waiting_on_you`, `only_human_left`, soft precedence order, edges onto a human blocker.
  - `tracker.py`: resolution, the merge rule, validation.
  - `board.py`: render, header, drift.
  - The existing 180 tests stay green.
- **The two-repo e2e test** gains a human ticket in the middle of the graph and a `ships_with` pair.
- **The ship template:** a unit test that the default template has every placeholder and nothing inlined in the skill.
- **Frontmatter:** all of it still parses (`yaml.safe_load`).
- **Not covered by tests:** the adapters' prose against real Jira, GitHub and Linear. They need a live dry run per tracker.

## Left to the builder

- The exact header-line grammar of the local ticket files, and its parser.
- The wording of the adapter prose, and per-tool fallbacks where a native relationship is missing.
- Where `human-done` is offered in chat versus as a `/kinetic:status` hint.
- Whether `tracker.py` and `board.py` are separate modules or one.

## Designer's calls (check while reading)

- Ship opens PRs anyway when a human ticket is still open, and marks it as a merge blocker.
- Local ticket files stay in the run folder, not in the repo (`.scratch/`).
- Kinetic state stays authoritative; remote trackers are never read back.
- An edge onto a human blocker is satisfied when the blocker is `done`, whatever its edge type.
- `NEEDS_HUMAN` creates a new human ticket and blocks the original on it, instead of converting the original to human.
- The `release` edge is kept as it is rather than replaced by human tickets.
- The tracker is user-level only; a repo cannot switch it.
- "Blocks only" was selected together with the three new relationships; read as "keep blocks", not "add nothing".
