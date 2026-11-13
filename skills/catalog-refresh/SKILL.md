---
name: catalog-refresh
description: Learn repo labels and recipes from merged deliverables (tickets, epics, or a finished kinetic run) and add them to the repo catalog after the user approves each change. Takes ticket or epic keys, a tracker query, or a run directory. Use when the user wants to catalog, label or learn from merged tickets, seed the catalog from past work, or when cleanup offers to catalog a run.
model: sonnet
argument-hint: "<keys...> | --query <query> | --run <run_dir>"
---

# Kinetic catalog-refresh

Read merged deliverables, work out which repos each needed and why, and propose repo labels and recipes for the catalog. Nothing is written until the user approves it. Run scripts as `kinetic <module> ...`.

A **deliverable** is a lone ticket, or an epic with all its children, cataloged as one unit. A **recipe** is one kind of change: its title, when to use it, its parameters (the variable part, such as `<ASSET_CLASS>`), and per repo what it is needed for.

Input, one of:

- `Keys: <ticket or epic keys...>`
- `Query: <tracker query>` (the tracker's own search: JQL for Jira, a search string for GitHub or Linear)
- `Run: <run_dir>` (passed by `cleanup`)

Ask the user with the harness's question tool when the profile names one (`kinetic harness` prints it under `Question tool:`; `none` means chat).

## 1. Is a catalog set?

`kinetic catalog show`. Exit 1 means no folder is set:

- started by the user: offer `/kinetic:catalog-setup` and stop;
- started by another skill: print `No catalog folder set; skipped` and return.

## 2. Resolve the batch

- **Keys:** read each through the tracker adapter (`kinetic tracker resolve` names it; read `trackers/<name>.md`). An epic is expanded to its children; the epic key is the deliverable.
- **Query:** run it through the tracker adapter's search. With more than about 20 results, say how many and ask before going on.
- **Run:** the run is one deliverable, keyed by its ref when it has one, else the run id. Scope is the spec and tickets in `kinetic state load --run <run_dir>`, repos are `state.repos`, merged PRs are the integration-branch PRs (`gh pr list --head kinetic/<run-id>/integration --state merged --json number,url,title`, run from each repo's clone path).

Then `kinetic catalog ledger --keys <keys...>`: drop every key already cataloged and name them in one line.

## 3. Gather, per deliverable (agent; ask nothing)

1. **Scope:** summary, description and comments through the tracker adapter, plus at most one level of linked docs.
2. **Merged PRs** (skip for `Run:`): for the deliverable key, the epic key and each child key, search the saved GitHub orgs (`kinetic discover settings` prints `github_orgs`):
   `gh search prs "<KEY>" --owner <org> --json repository,number,title,state,url --limit 50 --jq '.[] | select(.title | contains("<KEY>")) | [.repository.name, .state, .url] | @tsv'`
   - Keep merged PRs. An empty result for a ticket past to-do: retry once; still empty, report "PR search returned nothing (may be index lag)".
   - A closed PR whose ticket or PR body says "superseded by", "consolidated into" or "replaced by": follow it to the replacement and use that one.
3. **Per repo, read** each merged PR's title, body and changed file paths (`gh pr view <num> --repo <org>/<repo> --json title,body,files`). Write one or two lines: what changed in that repo and why.

A deliverable with no merged PR is reported and skipped; never catalog from a description alone.

## 4. Group and generalize (agent)

- Read the catalog: `index.md`, `terms.md`, and the recipes whose when-to-use is close to a deliverable.
- **Group** deliverables that touch the same repos for the same reasons and differ only in some value (an asset class, a product, a report). Match each group against existing recipes first; a match extends that recipe instead of creating a near-duplicate.
- **Parameters** come from what differs between members of a group (HOME_SECURED and HELOC become `<ASSET_CLASS>`). For a single-deliverable group, infer the parameter and mark it inferred in the review.
- **What-for lines:** two or three per repo, generic in the parameter, naming the place in the code when the PRs show it. Short.
- **Terms:** map every domain word to a term in `terms.md`; propose a new term (with meaning, synonyms, words to avoid) only when none fits. Never two terms for one idea (`onboard` and `onboarding`).

## 5. Review (you): one message per proposed recipe

Each message shows: title, when to use, parameters, each repo with its what-for lines and its strength after this change (always, usually, sometimes, seen once, with `<seen> of <of>`), the deliverables and PRs behind it, the repo term changes, and new terms. For an existing recipe, show only what changes. Deliverables that fit no group are single-source recipes, marked weak, reviewed the same way.

The user approves, edits or drops each item. "Not now" writes nothing, and the ledger stays as it was, so the same keys can be cataloged later.

## 6. Apply

Write the approved items to `changes.json` in the scratch area, in this shape:

```json
{"deliverables": [{"key": "...", "repos": ["..."], "prs": ["url"], "recipe": "slug or null"}],
 "recipes": [{"slug": "...", "title": "...", "when": "...", "parameters": [{"name": "...", "meaning": "...", "examples": ["..."]}], "terms": ["..."], "what_for": {"<repo>": ["line"]}}],
 "repos": [{"repo": "...", "org": "...", "owns": "optional one line", "terms": {"<term>": ["<key>"]}}],
 "terms": [{"term": "...", "meaning": "...", "synonyms": [], "avoid": []}]}
```

Never write counts: `kinetic catalog apply` derives them from the deliverables. Run `kinetic catalog apply --changes <scratch>/changes.json`. A refusal (key already cataloged, unknown term, unknown recipe, broken catalog file) writes nothing: report it, fix the change file, and apply again. Then report what was written.

## Rules

- Read-only until step 6. Never edit catalog files with edit tools; only `kinetic catalog apply` writes them.
- Never commit or push the catalog folder.
- One review message per recipe, never one per ticket.
