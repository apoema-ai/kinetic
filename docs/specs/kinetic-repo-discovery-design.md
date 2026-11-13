# Kinetic: repo discovery phase and init from the current directory

Status: draft for approval. Base: `27da680`. Builds on [kinetic-sdlc-pipeline-design.md](kinetic-sdlc-pipeline-design.md) and [kinetic-trackers-human-tickets-pr-template-design.md](kinetic-trackers-human-tickets-pr-template-design.md).

## Why

A run has to know its repos at intake, because the lane depends on how many there are. Often nobody knows that yet: the ticket says "show the carbon footprint per trip", and which of the team's twenty repos it touches only becomes clear after the grill, or after someone looks. Today kinetic either calls `find-ticket-repos`, a user skill that is not packaged (so most installs never have it), or asks the user, and it can only pick from repos already in `repos.json`. Worktrees are cut only at build, so grill, spec and tickets read the user's normal checkouts.

Separately, `/kinetic:init` with no arguments asks for repo paths even when the user is standing in the repo (or the folder of repos) they want to register.

## Goals

1. **Start a run without knowing its repos.** The run workspace is created with no repos. The repo set comes from the user's input, the grill, or discovery, in that order.
2. **A packaged discovery phase.** When the repo set is unclear, a `discover` phase finds candidates from sources the user approves: a base folder of checkouts, other sources the user names, and the GitHub organization.
3. **Few questions, batched.** One message to gather where to look, then discovery runs without asking, then one message to confirm. A follow-up round only when the result is empty, weak or incomplete.
4. **Worktrees for every chosen repo**, cut under `<run_dir>/worktrees/` when discovery ends, so spec and tickets read the run's own copies.
5. **Remember the answers.** The approved base folders and GitHub orgs are saved in `settings.json` and offered as defaults on the next run.
6. **`/kinetic:init` with no paths uses the current directory.**

## Non-goals

- GitLab, Bitbucket or other forges as a built-in source. The "other sources" question covers them in prose.
- Searching the whole disk or every folder the user has. Only approved base folders, one level deep.
- A `--repo` flag on `/kinetic:run`. A repo named in the ref text, or the registered repo the user runs from, seeds the candidates.
- Changing how a mono-repo is modelled: it stays one repo.
- Keeping `find-ticket-repos` or `checkout-ticket-repos` as optional companions.

## Anti-goals

- Discovery that asks one question per source, or one per repo.
- A repo joining the run without the user seeing it and why.
- A clone, a GitHub search, or a read of a source the user did not approve.
- A discovery loop with no end: weak results must reach the user, not loop.
- Writing config with the Write/Edit tools during a run (the isolation hook denies it, see 6).

## Decided by the user

- Discovery runs after the grill, or when the user's input already names a repo; it is a step for when the repo set is not clear.
- Sources: (1) a base folder where the user keeps checkouts, found in docs, AGENTS.md, CLAUDE.md or similar, used only after the user agrees; (2) any other source the user names; (3) the GitHub organization, only with permission.
- The questions are asked together up front, then discovery executes. If it finds nothing, or the result is low-confidence, flaky, too thin or incomplete, it asks the user again.
- A repo found on GitHub but not on disk: ask to clone it (recommended) or let the user clone it.
- The approved base folder and GitHub org are saved for the next run.
- Every repo in the ticket gets a worktree under the run workspace.
- Approach A (below). Written from scratch: `find-ticket-repos` is not available to evolve, and `wayfinder` is a multi-session planning tool, not a base for a one-step phase. Three ideas from wayfinder are borrowed (see 2).
- `/kinetic:init` without paths uses the current directory.

## Approaches

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | New `discover` phase skill plus a small `kinetic discover` script for the deterministic parts (list repos under a folder, save settings, register a repo) | One more phase and script; matches how every other phase works, testable, resumable after a crash | **Chosen** |
| B | Fold discovery into the grill | No new phase; but the grill is skipped when a spec is brought in, so discovery would need a second home anyway | Rejected |
| C | Skill text only, the agent lists folders and edits config itself | Smallest diff; config writes are denied by the isolation hook during a run, and repo listing becomes untestable | Rejected |

## Design

### 1. Phase order and lanes (`state.py`, `run/SKILL.md`, `guides/lanes.md`)

`PHASES` becomes `intake, grill, discover, spec, tickets, build, review, ship, retro, done`. `discover` runs in every lane, because it is where repos are registered and worktrees cut; when the repo set is already clear it asks nothing (see 3).

Lane selection moves:

- **Repo known at intake** (named in the ref text, or `/kinetic:run` invoked from inside a registered repo, or the tracker issue names its repo): intake picks the lane as today. Quick lane is only possible here.
- **Repo not known:** intake records `feature` as a provisional lane and starts at the grill. Discover sets the final lane: one repo is `feature`, two or more is `epic`.

New CLI: `kinetic state set-lane --run <dir> --lane <lane>`. It only moves between `feature` and `epic`, which run the same phases, so it is safe at any phase, including when a later discover pass adds a second repo. Moving into or out of `quick` is refused: quick skips grill, spec and tickets, so it is fixed at intake.

Quick lane order: intake, `discover` (confirm-only), the one-question breakdown gate, build.

Entry points in `lanes.md` change: "Spec, no tickets" starts at `discover` (was "tickets, repo detection first"). "Spec and tickets with edges" runs `discover` in confirm-only mode on the tickets' repos, then build. `--from build` and `/kinetic:implement` do the same for the one ticket's repo.

**Discover again later.** When the tickets phase needs a repo that is not in the run, the orchestrator runs the discover skill in confirm-only mode for it without changing the phase (it stays `tickets`), then returns to tickets. This happens before the breakdown gate, so the gate lists every repo the grant covers. No repo is added after the breakdown gate: if build finds a ticket whose repo is not in the run, it stops and sends the run back to the tickets phase, which asks the breakdown gate again.

**Removing a repo.** New CLI `kinetic state remove-repo --run <dir> --name <repo>`: refused while any ticket names the repo; otherwise drops it from `state.repos`. The orchestrator then runs `git worktree remove` on its integration worktree. Used when a later discover pass (after a re-grill or a rejected spec gate) drops a repo from the list.

### 2. The discover skill (`skills/discover/SKILL.md`, new)

A phase skill, run inline by the orchestrator like the others. Input: `Run: <run_dir>`, the ref, the candidate repos the grill or intake produced (each with where it came from), and the spec location if there is one.

Written in wayfinder's terms for who acts: **you** steps (the user answers; the agent never answers for them) and **agent** steps (no questions).

**Step 1, agent: is the set clear?** Clear means every candidate is registered in `repos.json`, came from a known place (named in the ref text, named by the tracker issue, the registered repo `/kinetic:run` was started from, or confirmed by the user in the grill), and nothing in the grill or spec names a component no candidate owns. Clear: print one line ("Repos: api, web, from the grill") and go to step 6. Not clear: continue.

**Step 2, agent: find base folders on its own.** Read `repo_roots` and `github_orgs` from `kinetic discover settings`. Read the instruction files the harness loads (user and project `CLAUDE.md`, `AGENTS.md`) and the README and AGENTS.md of each candidate repo, looking for a folder where the user keeps checkouts or a GitHub org name. Reading only; nothing leaves the machine.

**Step 3, you: one message, every question.** Asked with the harness's question tool, all at once:

1. Base folders: the saved ones and any found in step 2, each with where it was found, pre-selected when saved. "Any other folder?"
2. "Is there anything else that shows which repos this touches: a service catalog, an architecture doc, a wiki page, a CODEOWNERS file?" (free text, may be empty)
3. GitHub: "May I search the GitHub org(s) <saved or found>?" yes / no / another org. Skipped when `gh` is not authenticated, with a one-line note.

Save the approved folders and orgs right away: `kinetic discover remember --root <path> ... --org <org> ...`.

**Step 4, agent: run discovery, no questions.**

- Base folders: `kinetic discover scan --root <path> ...` lists the git repos (one level deep) with name, path, remote URL and whether they are registered. Match against the ticket, the grill notes, the glossary terms and the interfaces named so far, by repo name, README first lines and the remote's description.
- Other sources: read what the user gave (files, URLs the user named, using the harness's fetch tool) and extract repo names.
- GitHub: `gh repo list <org> --json name,description,repositoryTopics,url --limit 1000` for names and descriptions, and `gh search code --owner <org> "<interface name>"` for each interface the grill or spec names (the strongest signal that a repo produces or consumes it). Read-only calls.
- Every candidate gets a confidence and a one-line reason with its source:
  - **strong**: named by the user, the ticket or the spec; or a code hit on an interface the run produces or consumes;
  - **medium**: the name, description or topics match the run's domain terms;
  - **weak**: a keyword match only.

**Step 5, agent then you: judge, maybe ask again.** The result is not enough when there is no strong candidate, when an interface the grill or spec names has no repo that produces it (or none that consumes it), or when a source failed (auth, unreachable). Then ask one follow-up message: what was found, why it is not enough, what would help ("I found terramigo-api but nothing that serves the web app. Another org or folder?"), and go back to step 4 with the new sources. At most two follow-up rounds; after that go to step 6 with what there is.

**Step 6, you: confirm.** One message with two groups, wayfinder's split between what is known and what is still fog:

- **Candidates:** name, reason, source, confidence, and where it is: `registered`, `on disk, not registered`, or `GitHub only, not cloned`.
- **Suspected, unconfirmed:** weak matches, for the user to promote or ignore.

The user edits and approves the list. Refer to every repo by its name, never only by a path or URL (borrowed from wayfinder). The approval is recorded as a ruling (`add-ruling`), so the list and its reasons survive into PR bodies and recovery.

**Step 7, agent (asks only when needed): make every repo usable.**

1. `GitHub only, not cloned`: ask once for all of them: "Clone them into <first repo_root>? (recommended)" or "I'll clone them myself". On yes: `gh repo clone <org>/<name> <root>/<name>`. On no: list the clone commands and wait for the user to say done, then rescan. With no saved root, the same question asks where to clone.
2. `on disk, not registered`: `kinetic detect_repos <path> ...`; for each with a null verify, ask for the command (one message for all). Then `kinetic discover register --name <name> --path <clone path> --verify "<cmd>"`.
3. Set the final lane with `state set-lane` (see 1).
4. For each repo, cut the integration worktree as `build-loop.md` setup step 3 does today: base from `base_branch` in repo config (default `main`), `kinetic gitops worktree --repo <clone path> --dest <run_dir>/worktrees/<repo> --branch kinetic/<run-id>/integration --base <base>`, then `kinetic state set-repo`. A worktree that is already in state is kept.
5. Write `<run_dir>/discovery.md`: sources used, the approved list with reasons, the suspected ones not taken, and any follow-up rounds. Spec, tickets and ship read it.

### 3. Confirm-only mode

When step 1 finds the set clear, or the orchestrator calls discover with tickets already in hand, discover skips steps 2 to 6 and runs step 7. A repo not registered still gets the verify question; nothing else is asked.

A repo known only by name (a ticket brought in from a tracker) that is not in `repos.json`: run `discover scan` on the saved repo roots and match by directory name, then by the repo name at the end of the remote URL. One match: use it. None or several: ask the user for the path, in the same message as any verify question.

### 4. The `kinetic discover` script (`scripts/kinetic/discover.py`, new)

Python 3.9 stdlib, JSON out, like the other modules. Subcommands:

| Subcommand | Does |
|---|---|
| `settings` | Prints `{"repo_roots": [...], "github_orgs": [...]}` from `~/.config/kinetic/settings.json` (empty lists when missing). |
| `remember --root P ... --org O ...` | Adds to `repo_roots` (absolute, `~` expanded, must be an existing directory) and `github_orgs`, deduplicated, order kept, every other key untouched. Creates the file if missing. |
| `scan --root P ...` | For each root: if the root itself is a git work tree, that repo; otherwise each direct child that is a git work tree. Prints `[{name, path, remote, registered, registered_as}]`. `registered` compares real paths against `repos.json` entries. Skips unreadable children. |
| `register --name N --path P --verify CMD [--publish-snapshot C] [--pin C]` | Adds one entry to `repos.json`, keeping every other entry. Refuses an empty verify, and refuses a name already registered with a different path. |

`scan` is also what init uses for the current directory (see 7).

### 5. Build loop and tickets (`guides/build-loop.md`, `skills/tickets/SKILL.md`, `graph.py`)

- Build setup step 3 no longer creates worktrees. It checks that every repo a ticket names is in `state.repos`; a missing one means a ticket was added after discovery, so send the run back to `discover` in confirm-only mode for that repo. It still creates a missing worktree for a repo in state whose worktree directory is gone (recovery).
- Tickets: a ticket's `repo` must be a repo in the run. If slicing shows another repo is needed, the tickets skill says so and the orchestrator runs `discover` again in confirm-only mode for it, then returns to tickets.
- `graph validate` gains one error: an agent ticket whose `repo` is not in `state.repos`. Human tickets (no repo) are exempt.
- Tickets and spec explore code in `state.repos[<repo>].path`, the run's worktree, not the user's checkout.

### 6. Isolation and hooks

The isolation hook denies Write/Edit outside the run directory and the repos in state. Because worktrees now exist from discover onward, the hook changes: the repos in state are writable only once the breakdown gate is recorded approved (`gates.breakdown.approved`). Before that, only the run directory is writable, so spec and tickets cannot edit a worktree before the grant exists, and `record_edit` cannot mark verify stale early.

Discover never writes config through those tools: `remember` and `register` are Bash calls to the script, which the hook does not path-check, the same way `state` writes today. `git clone` and `gh repo clone` are not hook-confirmed (`clone` is in `NON_PUSH`); the step 7 question is the consent. GitHub reads (`gh repo list`, `gh search code`) are read-only and need no confirmation.

### 7. Init from the current directory (`skills/init/SKILL.md`)

With no path arguments, step 1 runs `kinetic discover scan --root "$PWD"`:

- The current directory is inside a git work tree: register that repo (its top level).
- It is a folder holding git repos: ask which to register, all pre-selected. Also offer to save the folder as a repo root for discovery (`discover remember`).
- Neither: ask for paths, as today.

With path arguments, unchanged.

### 8. Removed companions

`find-ticket-repos` and `checkout-ticket-repos` are dropped: from `doctor.py`'s `SKILLS`, its tests, `lanes.md`, `run/SKILL.md`, `build-loop.md` and the README's companion list. `resolving-merge-conflicts` stays.

### 9. Docs and status

- README: the flow diagram gets `[discover]` after `[grill]`; "Lanes and entry points", the example runs (the epic example shows a discovery round) and the Configuration section (`repo_roots`, `github_orgs`) are updated.
- `/kinetic:status` already prints the phase; nothing else changes. The installers pick up `skills/discover/` through their existing `skills/*/SKILL.md` glob; the tests' `SKILL_NAMES` sets gain `discover`.
- `GLOSSARY.md`: **Repo root** (a folder whose child repos discovery may scan; avoid: workspace, base dir), **Discovery** (the phase that settles a run's repos; avoid: repo detection).

## Compatibility

- Runs started before this change keep valid `phase` values. A run in `grill` continues into `discover`. A run already in `spec` or `tickets` has an empty `state.repos` (worktrees used to be cut at build): when it reaches the breakdown gate or build setup, the orchestrator runs discover in confirm-only mode on its tickets' repos first. Those repos are registered, so that pass asks nothing and only cuts the worktrees. No migration script.
- The integration branch is cut from the local base branch at discover time instead of at build, same as today otherwise: kinetic does not fetch. A long gap between discover and build means the branch starts from an older base, as it would today with an old local checkout.
- `settings.json` without `repo_roots` / `github_orgs` reads as empty lists. `repos.json` is unchanged in shape.
- Harnesses: the skill uses each harness's question tool through the harness profile, as the other phase skills do. Every guarantee in step 3 to 7 (one batched message, consent before clone) is Instructed, not Enforced.

## Testing

Script behavior gets unit tests next to the existing ones (`tests/test_state.py`, new `tests/test_discover.py`, `tests/test_graph.py`, `tests/test_doctor.py`, `tests/test_install.py`):

- `state`: `discover` sits between `grill` and `spec`; `set-lane` moves between `feature` and `epic` at any phase; refuses moving into or out of `quick`; refuses an invalid lane. `remove-repo` drops an unused repo; refuses one a ticket names.
- `isolation` hook: a write inside a repo in state is denied before the breakdown gate is approved and allowed after; a write in the run directory is allowed in both cases.
- `discover settings`: missing file gives empty lists.
- `discover remember`: creates the file; merges and dedupes; keeps other keys; rejects a root that is not a directory.
- `discover scan`: a root that is a repo; a folder of repos (one level only, a nested repo two levels down is not listed); a non-git child is skipped; `registered` matches by real path (symlinked path counts).
- `discover register`: adds an entry and keeps others; refuses an empty verify; refuses a name taken by another path; same name and path is a no-op.
- `graph validate`: an agent ticket whose repo is not in `state.repos` is an error; a human ticket without repo is not.
- `doctor`: the two dropped skills are no longer checked.
- `install`: `discover` is installed on every harness.

The skill text (steps 1 to 7, init's cwd flow) is checked by a smoke run per harness, as in `docs/smoke/`.

## Left to the builder

- Exact wording of the questions and of `discovery.md`.
- How many interface names to code-search when the grill names many (a sensible cap, say 10).
- Whether `scan` reads the remote URL with `git config --get remote.origin.url` or `git remote get-url origin`.

## Designer's calls (check while reading)

- `discover` runs in every lane; when the set is clear it asks nothing and only registers repos and cuts worktrees.
- Unknown repos at intake means a provisional `feature` lane; the quick lane needs the repo known at intake.
- `set-lane` only moves between `feature` and `epic`; quick is fixed at intake.
- A repo can join the run only before the breakdown gate; a later need goes back to tickets and re-asks the gate.
- Repo worktrees are read-only (isolation hook) until the breakdown gate is approved.
- In-flight runs heal themselves through a confirm-only discover pass; no migration script.
- A repo known only by name is found by scanning the saved repo roots; the user is asked only when that finds none or several.
- `state remove-repo` is added for repos a later discover pass drops.
- Base folders are scanned one level deep only.
- Clones go into the first saved repo root.
- At most two follow-up rounds before confirming with what there is.
- The confirm approval is recorded as a ruling, and the result is written to `<run_dir>/discovery.md`.
- A repo needed later (tickets phase) goes back through discover in confirm-only mode, enforced by a new `graph validate` error.
- Running `/kinetic:run` from inside a registered repo seeds it as a candidate; no `--repo` flag.
- Init in a folder of repos also offers to save that folder as a repo root.
