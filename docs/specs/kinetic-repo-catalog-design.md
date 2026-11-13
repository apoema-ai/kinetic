# Kinetic: a repo catalog learned from merged work

Status: draft for approval. Builds on [kinetic-repo-discovery-design.md](kinetic-repo-discovery-design.md) and follows the setting pattern of [kinetic-bare-repos-design.md](kinetic-bare-repos-design.md). Brainstormed 2026-11-13. "Decided by the user" holds only what the user said; "My calls" holds what I chose and the user has not yet confirmed.

## Why

When the user starts a ticket they have a ticket description and maybe a Confluence page, but nothing that says which repos the work touches. `discover` matches candidates against repo names, README lines and GitHub descriptions: it has no memory of what similar work touched before. `find-ticket-repos` (a personal skill, not packaged with kinetic) already treats a few hand-written "domain skills that name every repo a change type needs" as strong evidence; this design learns that kind of knowledge from merged deliverables instead of writing it by hand.

Example: INV-24468 onboarded the HOME_SECURED asset class into the investor warehouse. Its merged PRs touched `investor-warehouse-pledge-srvc` (nightly workflow trigger, ingest and origination tiers), `investor-mgt-srvc` (preset investment account, warehouse tests, account-to-asset-class link) and `k8s-template` (asset position load and nightly workflow processes enabled for the class). The catalog keeps that as a recipe, "Onboard an asset class in the investor warehouse pledge service", generalized to any asset class, and labels each repo with domain terms (`warehouse`, `pledge`, `asset-class`, `onboarding`, `investor`).

## Goals

1. **A catalog-refresh skill** (`/kinetic:catalog-refresh`) that reads merged deliverables (tickets or epics) and proposes repo labels and recipes from their scope and merged PRs.
2. **Batch first.** It runs over a batch of tickets, so the catalog can be seeded from past work, and over a single ticket.
3. **Recipes are short and generic.** A recipe describes a kind of change with its variable part as a parameter (`<ASSET_CLASS>`), never one ticket's instance.
4. **Nothing is written without the user's approval**, however the skill was started.
5. **The user sets the catalog folder.** Unset means no catalog behavior anywhere.
6. **`discover` reads the catalog** as a source of candidates with reasons.
7. **`cleanup` offers to catalog** the run it just cleaned.

## Non-goals

- A hook trigger. The user has no proposal for one yet. The skill takes the same input a hook would pass (see 3), so one can be added later without changing it.
- Committing or pushing the catalog. If the folder sits inside a git checkout, that is how a team shares it; committing stays the user's call.
- Cataloging open or unmerged work.
- A search engine or embeddings. The catalog is plain files an agent reads.
- Editing `find-ticket-repos` or any other personal skill.

## Anti-goals

- A recipe that is one ticket restated ("Onboard HOME_SECURED ...").
- Label drift: `onboard` and `onboarding` as two terms.
- One ticket defining a repo: a term or recipe repo seen once must read as weak.
- A write to the catalog the user did not see.
- A review message per ticket in a batch.
- `discover` skipping its confirm step because a recipe matched.

## Decided by the user

- Two outputs: **labels** on repos (domain terms, used to find candidate repos) and **recipes** (a title plus, per repo, what it is needed for).
- A recipe is built from the ticket scope plus a reasoning over each involved repo's merged PRs, kept short, and generalized beyond the instance.
- Purpose: help an agent pick candidate repos for a scope given in a prompt; the main consumer is kinetic's `discover`.
- Triggered manually or invoked by another skill such as `cleanup`; a hook may come later.
- The storage folder is set by the user, inspired by `setup-bare-repos`.
- Approve first: proposed changes are shown and approved before anything is written, also when `cleanup` starts it.
- Batch runs over many tickets are wanted.
- Batch input: ticket keys, epic keys, or a JQL query.
- `discover` uses the catalog as proposed in "Design 6".
- The format and granularity in "Design 2" were accepted as "the right track".
- This document lives in `docs/specs/`.

## Design

### 1. Setting (`scripts/kinetic/catalog.py`, new)

`~/.config/kinetic/settings.json` gains `catalog_dir` (a string), next to `bare_dir`. Same atomic write and bad-JSON refusal as `bare`.

| Command | Does |
|---|---|
| `kinetic catalog detect [--cwd P]` | Candidates and one recommendation: the saved `catalog_dir`; else a folder at or above `--cwd` (up to the git top level) that looks like a catalog (`index.md` and `recipes/`); else none. |
| `kinetic catalog set --dir P [--create]` | Saves `catalog_dir`. With `--create`, creates the folder and the empty layout (2); refuses to overwrite existing files. |
| `kinetic catalog show` | Prints `catalog_dir` or `null`; exit 1 when unset. |
| `kinetic catalog ledger --keys K ...` | For each key: cataloged or not, and what it fed. |
| `kinetic catalog apply --changes F` | Applies an approved change file (5) atomically: writes recipes, repo profiles, terms, then regenerates `index.md` and appends to `ledger.json`. Refuses terms not in `terms.md` after the change. |
| `kinetic catalog index` | Regenerates `index.md` from the files (also run by `apply`). |
| `kinetic catalog lint` | Checks every file's frontmatter, term references, and that recipe repo counts match their sources. |

Python 3.9 stdlib, JSON out, like the other modules.

### 2. Format and granularity

```
<catalog_dir>/
  index.md            generated: one line per recipe and per repo
  terms.md            controlled vocabulary
  repos/<repo>.md     repo profile
  recipes/<slug>.md   one kind of change
  ledger.json         deliverables already cataloged
```

Markdown with a JSON frontmatter block (fenced by `---`), so the stdlib script can parse it and agents and people can read and edit it.

**`terms.md`**: one entry per term: the term (lowercase, kebab-case), a one-line meaning, synonyms, words to avoid. Every term used in a profile or recipe must be listed here.

**Repo profile (`repos/<repo>.md`)**: frontmatter `{repo, org, terms: {<term>: <count>}, sources: {<term>: [<key>...]}, updated}`; body: one "owns" line, written from the PRs, not from memory. A term's count is the number of cataloged deliverables that gave it.

**Recipe (`recipes/<slug>.md`)**: frontmatter `{slug, title, parameters: [{name, meaning, examples}], terms: [...], repos: [{repo, seen, of}], sources: [{key, prs: [url...]}], updated}`; body:

```markdown
# Onboard an asset class in the investor warehouse pledge service

**When to use:** adding a new <ASSET_CLASS> to the warehouse pledge flow (nightly workflow, pledge eligibility, line balance).

## investor-warehouse-pledge-srvc (always, 3 of 3)
- add <ASSET_CLASS> to the nightly warehouse workflow trigger
- ingest tier and origination tier for <ASSET_CLASS>

## investor-mgt-srvc (always, 3 of 3)
- preset investment account for <ASSET_CLASS> in the data-generation context
- extend the warehouse tests to <ASSET_CLASS>
- link the investment accounts to <ASSET_CLASS>

## k8s-template (usually, 2 of 3)
- enable <ASSET_CLASS> for the asset position load processes
- enable <ASSET_CLASS> for the nightly workflow processes
```

Strength from `seen/of`: **seen once** (one source), else **always** (every source), else **usually** (at least half), else **sometimes**. "What for" lines name the place in the code when the PRs show it; two or three per repo.

**Granularity rules:**

1. A recipe is one kind of change. Two deliverables share a recipe when they touch the same repos for the same reasons and differ only in parameter values.
2. The unit is the deliverable: an epic with all its children's merged PRs, or a lone ticket.
3. Re-running is safe: a key in the ledger is skipped. A deliverable that matches an existing recipe raises its counts and adds a new repo as "seen once".
4. Terms come only from `terms.md`; a new word is mapped to an existing term or proposed as a new one.

**`ledger.json`**: `{<key>: {cataloged_at, recipe: <slug or null>, repos: [...]}}`.

**`index.md`** (generated): a recipe section (`slug — title — when to use — repos with strength`) and a repo section (`repo — top terms with counts`). `discover` reads this first.

### 3. The catalog-refresh skill (`skills/catalog-refresh/SKILL.md`, new)

Input (one of):

- `Keys: <ticket or epic keys...>`
- `Query: <tracker query>` (JQL with the Jira tracker; the tracker's own search otherwise)
- `Run: <run_dir>` (from `cleanup`): the deliverable is the run (its ref key when it has one); scope comes from the spec and tickets in state, repos from `state.repos`, and merged PRs from the integration-branch PRs `cleanup` already found (`gh pr list --head kinetic/<run-id>/integration`).

Steps:

1. **Catalog set?** `kinetic catalog show`. Unset: started by the user, offer `/kinetic:catalog-setup` and stop; started by another skill, print one line ("No catalog folder set; skipped") and return.
2. **Resolve the batch.** Expand epics to their children (the epic stays the deliverable). A query with more than about 20 results asks before going on. `kinetic catalog ledger` drops keys already cataloged; name them in one line.
3. **Gather, per deliverable (agent).** Scope from the tracker adapter (summary, description, comments, one level of linked docs). Merged PRs: from state for a run; otherwise search the PRs by key (deliverable key, epic key, children) with `gh` in the user's GitHub orgs (`github_orgs`), keep `MERGED`, follow "superseded by / consolidated into" to the replacement. Read each PR's title, body and changed file paths; write one short reasoning per repo: what changed and why. A deliverable with no merged PR is reported and skipped.
4. **Group and generalize (agent).** Group deliverables by rule 2.1. Match each group against existing recipes first. Name the parameter(s) from what differs between members (a batch reveals it; a single deliverable has it inferred and marked so). Map words to `terms.md`.
5. **Review (user), one message per proposed recipe:** title, when-to-use, parameters, repos with strength and what-for lines, sources, the repo profile term changes, new terms. For an existing recipe, only the changes. The user approves, edits or drops each item. Deliverables that fit no group are single-source recipes, marked weak, reviewed in the same way.
6. **Apply.** Write the approved items to a change file in the scratch area and run `kinetic catalog apply --changes <file>`. Report what was written. "Not now" writes nothing and leaves the ledger untouched.

Read-only until step 6. No commit, no push.

### 4. Setup skill (`skills/catalog-setup/SKILL.md`, new)

User-only. `kinetic catalog detect`; ask (harness question tool) with the recommended folder first, then the current folder, then another; show the layout that will be created; on yes, `kinetic catalog set --dir <P> --create`. Say that putting the folder in a git checkout shares it with whoever uses that checkout, and that kinetic never commits it.

### 5. Change file

JSON written by the skill, read by `apply`: `{deliverables: [{key, repos, prs, recipe}], recipes: [{slug, title, when, parameters, terms, what_for: {<repo>: [line]}}], repos: [{repo, org, owns, terms: {<term>: [<key>]}}], terms: [{term, meaning, synonyms, avoid}]}`. Each deliverable becomes a recipe source and a ledger entry; `apply` derives every count from the sources and renders the bodies, so the skill never writes a count or a body. `kinetic catalog index` re-renders bodies and `index.md` from the frontmatter after a hand edit.

### 6. `discover` (`skills/discover/SKILL.md`)

Step 4 gains a first source, used when `kinetic catalog show` succeeds; local files, no permission needed:

- Read `index.md`; match the run's scope (ref, grill notes, spec, glossary terms) against recipe when-to-use lines and repo terms; open the matching recipes.
- Confidence: a recipe repo marked **always** is strong, **usually** is medium, **sometimes** and **seen once** are weak; a terms-only match is medium at most.
- Reason line names the recipe: `recipe onboard-asset-class-warehouse-pledge: always (3 of 3)`.
- The approved repos' what-for lines go into `discovery.md`.
- A catalog match never skips step 6 (confirm).

Step 1 ("is the set already clear?") is unchanged: a recipe match alone does not make the set clear.

### 7. `cleanup` (`skills/cleanup/SKILL.md`)

After step 5 (report), when `kinetic catalog show` succeeds and at least one repo's PR is merged: ask once "Catalog this run's merged work?". On yes, run the catalog-refresh skill's steps with `Run: <run_dir>`. Cleanup's removals never wait on it. This makes cleanup the one skill that invokes another; its text says so.

## Testing

`tests/test_catalog.py` (temp `HOME`): detect precedence; set with and without `--create`; show exit codes; ledger lookup; apply merges counts, adds a new repo as seen-once, refuses an unknown term, regenerates the index, is atomic on a bad change file; lint catches a count that does not match sources. `test_skill_text.py`: the two new skill names, `catalog-setup` user-only, no Claude-only tool names. A smoke run seeds a catalog from a batch of three merged tickets and runs `discover` against a fourth.

## My calls (unconfirmed by the user)

- Skill names `catalog-refresh` (user-chosen) and `catalog-setup`; script `kinetic catalog`.
- `catalog_dir` lives in kinetic's `settings.json`, not `~/.claude/`.
- JSON frontmatter in Markdown, so the stdlib can parse it.
- Strength thresholds: seen once = one source; always = every source; usually = at least half; sometimes = the rest (added during planning: the first three left 2 of 5 unlabeled).
- The batch-size question at about 20 results.
- From `cleanup`, the catalog question comes after the report, as a separate question.
- `cleanup` is the only skill allowed to invoke another; `discover` reads the files directly.
- A deliverable with no merged PR is skipped, not cataloged from its description alone.
- The catalog-refresh skill is model-invocable (so `cleanup` and later a hook can call it); `catalog-setup` is user-only.

## Left to the builder

- Exact wording of the review message and of `index.md`.
- Slug rules for recipes.
- How many linked docs to read per deliverable (one level, as `find-ticket-repos` does).
- Frontmatter field order.
