---
name: discover
description: Settle which repos a kinetic run touches. Asks the user once where to look (base folders of checkouts, other sources, the GitHub org), searches them, confirms the list with the user, registers new repos and cuts each repo's integration worktree. Use at the discover phase of a kinetic run.
model: sonnet
---

# Discover

Find the repos this run touches, get the user to confirm them, and make each one usable: registered in `repos.json`, with its integration worktree under the run directory. This skill never invokes another skill.

The orchestrator passes:

- `Run: <run_dir>` (the run directory, `<workspace>/<run-id>/`) and the ref;
- `Candidates:` the repos known so far, each with where it came from (the ref text, the tracker issue, the repo `/kinetic:run` was started from, the grill), or none;
- `Spec:` the spec location, if there is one;
- `Mode: full` or `Mode: confirm-only` (tickets already in hand, or a repo added later by the tickets phase).

Run scripts as `kinetic <module> ...`. Ask the user with the harness's question tool when the profile names one (`kinetic harness` prints it under `Question tool:`; `none` means chat).

Each step below is either **agent** (you work alone and ask nothing) or **you** (the user answers). On a **you** step, never answer for the user, never guess their answer, and ask every question of that step in one message.

Never write `~/.config/kinetic/` files with the edit tools: the isolation hook denies them during a run. Config changes go only through `kinetic discover remember` and `kinetic discover register`. Reading a source sends nothing off the machine; only the GitHub calls in step 4 reach the network, and only with the user's permission.

## Mode: confirm-only

Skip steps 2 to 6 and run step 7 on the candidates. A candidate known only by name that is not in `~/.config/kinetic/repos.json`: run `kinetic discover settings`, then `kinetic discover scan --root <each repo_root>`, and match by directory name, then by the repo name at the end of the remote URL. One match: use it. None or several: ask the user for the path, in the same message as any verify question from step 7.

## Mode: full

### 1. Is the set already clear? (agent)

The set is clear when every candidate is registered in `repos.json`, came from a known place (named in the ref text, named by the tracker issue, the registered repo the run was started from, or confirmed by the user in the grill), and nothing in the grill notes (`<run_dir>/docs/`) or the spec names a component that no candidate owns.

Clear: print one line, for example `Repos: api, web (from the grill)`, and go to step 7. Not clear: continue.

### 2. Look for base folders on your own (agent)

- `kinetic discover settings` prints the saved `repo_roots` and `github_orgs`.
- Read the instruction files the harness loads (the user-level and project-level `CLAUDE.md` and `AGENTS.md`) and the README and `AGENTS.md` of each candidate repo. Look for a folder where the user keeps checkouts, and for a GitHub organization name. Note where you found each.

### 3. Ask once (you)

One message, all three questions:

1. **Base folders.** List the saved ones (pre-selected) and the ones found in step 2, each with where it was found. Ask which to use and whether there is another folder where they keep checkouts.
2. **Other sources.** "Is there anything else that shows which repos this touches, such as a service catalog, an architecture doc, a wiki page or a CODEOWNERS file?" Free text; empty is fine.
3. **GitHub.** "May I search the GitHub org(s) <saved or found>?" with the choices yes, no, or another org. When `gh auth status` fails, skip this question and say in one line that GitHub search is off until `gh` is logged in.

Save the approved folders and orgs right away: `kinetic discover remember --root <path> ... --org <org> ...`.

### 4. Search (agent)

Search every approved source, asking nothing:

- **Base folders.** `kinetic discover scan --root <path> ...` lists the git repos one level deep, with name, path, remote and whether each is registered. Match them against the ref, the grill notes, the glossary terms and the interfaces named so far, using the repo name, the first lines of its README and its remote.
- **Other sources.** Read what the user named (files, or URLs they gave, with the harness's fetch tool) and pull out repo names.
- **GitHub.** `gh repo list <org> --json name,description,repositoryTopics,url --limit 1000` for names and descriptions. For each interface the grill or spec names (an endpoint, a client method, an event, a schema), `gh search code --owner <org> "<interface name>"`: a hit is the strongest sign that a repo produces or consumes it. Search at most 10 interfaces, the ones the run produces or consumes first.

Give every candidate a confidence and a one-line reason with its source:

- **strong**: named by the user, the ticket or the spec; or a code hit on an interface the run produces or consumes;
- **medium**: its name, description or topics match the run's domain terms;
- **weak**: a keyword match only.

### 5. Is it enough? (agent, then maybe you)

The result is not enough when any of these holds:

- there is no strong candidate;
- an interface the grill or spec names has no repo that produces it, or none that consumes it;
- a source failed (not authenticated, unreachable, unreadable).

Then ask one follow-up message: what you found, why it is not enough, and what would help. Example: "I found terramigo-api, but nothing that serves the web app. Is there another org or folder?" Save any new folder or org with `kinetic discover remember` and go back to step 4 with the new sources.

At most two follow-up rounds. After the second, go to step 6 with what you have and say what is still missing.

### 6. Confirm (you)

One message, in two groups:

- **Candidates:** name, reason, source, confidence, and where it is: `registered`, `on disk, not registered`, or `GitHub only, not cloned`.
- **Suspected, unconfirmed:** the weak matches, for the user to add or ignore.

Always name a repo; never show only a path or URL. The user edits and approves the list. Record the approval as a ruling:

```
kinetic state add-ruling --run <run_dir> --what "repos: <names>" --why "<one reason per repo>" --cost "a missing repo is found at tickets and costs a confirm-only pass; an extra repo costs an unused worktree"
```

## 7. Make every repo usable (agent; asks only when needed)

Ask the questions of this step together, in one message, and only those that apply.

1. **GitHub only, not cloned.** One question for all of them: "Clone them into <first repo_root>?" (recommended) or "I'll clone them myself". With no saved repo root, the same question asks where to clone. On yes: `gh repo clone <org>/<name> <root>/<name>` for each. On "I'll clone them": print the clone commands, wait for the user to say they are done, then rescan with `kinetic discover scan`.
2. **On disk, not registered.** `kinetic detect_repos <path> ...` proposes each verify command. Ask for the command of every repo whose verify is null, in one message. Then, for each: `kinetic discover register --name <name> --path <clone path> --verify "<cmd>"`.
3. **Lane.** Mode full only, and only when the lane is not `quick`: one repo is `feature`, two or more is `epic`: `kinetic state set-lane --run <run_dir> --lane <lane>`.
4. **Worktrees.** For each repo not yet in `state.repos` (read it with `kinetic state load --run <run_dir>`): find its base branch (`base_branch` in its repo config, default `main`), then:
   - `kinetic gitops worktree --repo <clone path> --dest <run_dir>/worktrees/<repo> --branch kinetic/<run-id>/integration --base <base>`
   - `kinetic state set-repo --run <run_dir> --name <repo> --path <run_dir>/worktrees/<repo> --integration-branch kinetic/<run-id>/integration`

   A repo already in state keeps its worktree. The integration branch is never just `kinetic/<run-id>`: git cannot hold both that and `kinetic/<run-id>/<id>`.
5. **Record.** Write or update `<run_dir>/discovery.md` with:
   - the sources used, and the ones the user declined;
   - the approved repos with their reasons and sources;
   - the suspected repos the user did not take;
   - each follow-up round: what was missing and what the user added.

   Spec, tickets and ship read this file.

## Rules

- Never add a repo to the run that the user has not seen with its reason.
- Never clone, search GitHub, or read a source the user did not approve.
- One message per **you** step; never one question per source or per repo.
- Never loop past two follow-up rounds.
