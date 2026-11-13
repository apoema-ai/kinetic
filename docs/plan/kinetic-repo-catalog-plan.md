# Kinetic repo catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user-set catalog folder of repo profiles and recipes learned from merged deliverables, filled by `/kinetic:catalog-refresh` (approve first, batch-capable), and read by `discover`.

**Architecture:** One new stdlib module, `scripts/kinetic/catalog.py`, does the deterministic parts: the `catalog_dir` setting, reading and writing catalog files, merging an approved change file, regenerating the index, and lint. Two new skills carry the judgment: `catalog-setup` (user-only) and `catalog-refresh`. `discover` and `cleanup` get small text changes.

**Tech Stack:** Python 3.9 stdlib only, `unittest`, markdown skills.

**Spec:** [docs/specs/kinetic-repo-catalog-design.md](../specs/kinetic-repo-catalog-design.md)

## Global Constraints

- Python 3.9 stdlib only; every subcommand prints JSON on stdout. Errors go to stderr with exit 1, like `discover.py`.
- Setting key: `catalog_dir` (string) in `~/.config/kinetic/settings.json`. Read and write it through `config._load` and an atomic write (tmp file plus `os.replace`). Keep every other key. Refuse bad JSON before writing anything.
- Unset `catalog_dir` means no catalog behavior anywhere.
- Layout: `index.md`, `terms.md`, `repos/<repo>.md`, `recipes/<slug>.md`, `ledger.json`.
- Catalog files are Markdown with a JSON frontmatter block between a `---` line and the next `---` line.
- Strength from `seen`/`of`: **always**, **usually**, **seen once** (see Task 2 for the exact rule).
- Nothing is written to the catalog without the user's approval. Kinetic never commits or pushes the catalog.
- Skill names: `catalog-refresh` (model-invocable) and `catalog-setup` (user-only: `disable-model-invocation: true` and `triggers: [user]`). Script: `kinetic catalog`.
- Skill text names no Claude-only tool, no concrete model in the body, and no `${CLAUDE_PLUGIN_ROOT}` (enforced by `tests/test_skill_text.py`).
- Tests: one module with `PYTHONPATH=scripts python3 -m unittest tests.test_<name>`; the full suite with `PYTHONPATH=scripts python3 -m unittest discover -s tests`.
- Commit messages start with `kinetic-repo-catalog: `. No AI co-author trailer.
- Work on branch `kinetic-repo-catalog`, never on `main`.

## Review Focus

1. **A change file naming a deliverable already in the ledger** (a re-run racing an earlier one): `apply` refuses the whole file and writes nothing. Test: `test_apply_refuses_key_already_in_ledger` (Task 3).
2. **A term in a recipe or repo that is neither in `terms.md` nor in the change's `terms`** (label drift): `apply` refuses and writes nothing. Test: `test_apply_refuses_unknown_term` (Task 3).
3. **Hand-edited catalog files with broken frontmatter** (the folder is meant to be edited by people): `lint` reports the file and line, and `apply` refuses before writing. Tests: `test_lint_reports_bad_frontmatter`, `test_apply_refuses_when_catalog_file_is_broken` (Tasks 2 and 3).
4. **A recipe source that touched 2 of 5 repos' worth of deliverables** (between "seen once" and "usually"): it must not show as "usually". Test: `test_strength_thresholds` (Task 2).
5. **`set --create` on a folder that already holds a catalog or unrelated files**: it creates only the missing parts and never overwrites. Test: `test_set_create_keeps_existing_files` (Task 1).

---

### Task 0: Branch

- [ ] **Step 1:** `git -C /Users/rmendes/workspace/lab/kinetic switch -c kinetic-repo-catalog`
- [ ] **Step 2:** Run the full suite once and note the baseline count. Expected: OK.

### Task 1: The `catalog_dir` setting: `detect`, `set`, `show`

**Files:**
- Create: `scripts/kinetic/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces: `SETTINGS: Path`; `show(path=None) -> str | None`; `set_dir(d: str, create: bool = False, path=None) -> dict` returning `{"catalog_dir": str, "created": [relative paths]}`; `detect(cwd: str, path=None) -> dict` returning `{"existing_config": str|None, "candidates": [{"path", "reason"}], "recommendation": str|None}`; `is_catalog(d: str) -> bool`; `init_layout(d: Path) -> list[str]`. CLI: `kinetic catalog detect [--cwd P]`, `set --dir P [--create]`, `show`.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog.py` (temp dir, settings path passed explicitly, as in `test_discover.py`):
  - `test_show_unset_is_none`: missing file gives `None`. CLI `show` exits 1 and prints `null`.
  - `test_set_saves_and_keeps_other_keys`: settings `{"tracker": "jira"}`, then `set_dir(d)`, then the file has both keys and `show()` returns the real path of `d`.
  - `test_set_refuses_missing_dir_without_create`: raises `ValueError("not a directory: ...")`, and the file is unchanged.
  - `test_set_create_makes_layout`: `created == ["index.md", "terms.md", "repos", "recipes", "ledger.json"]`. `ledger.json` is `{}`. `terms.md` frontmatter is `{"terms": {}}`.
  - `test_set_create_keeps_existing_files`: pre-existing `terms.md` with one term and an unrelated `notes.txt` are untouched, and only the missing parts are listed in `created`.
  - `test_set_refuses_bad_json_settings`: raises `config.ConfigError`, file unchanged.
  - `test_detect_prefers_saved`: saved dir is the recommendation with reason `saved`.
  - `test_detect_finds_catalog_above_cwd`: a git repo with `docs/catalog/` holding `index.md` and `recipes/`, cwd `docs/catalog/recipes`. The recommendation is `docs/catalog` with reason `catalog at or above the current folder`. The walk stops at the git top level.
  - `test_detect_none`: no saved dir, no catalog, so `recommendation` is `None`.
- [ ] **Step 2:** Run `PYTHONPATH=scripts python3 -m unittest tests.test_catalog`. Expected: FAIL (`No module named kinetic.catalog`).
- [ ] **Step 3:** Implement the functions above and `main(argv)` in `scripts/kinetic/catalog.py`, reusing `discover._write` and `discover._real` (import them, don't copy them). `is_catalog(d)` means `index.md` is a file and `recipes/` is a directory. `detect` walks from `cwd` up to `git rev-parse --show-toplevel`, or checks `cwd` only when not in git. `init_layout` writes `terms.md` and `index.md` through Task 2's `write_doc` and `render_index`. Until Task 2 lands, keep them in this module as the minimal version Task 2 then completes.
- [ ] **Step 4:** Run the module tests. Expected: PASS.
- [ ] **Step 5:** Commit `kinetic-repo-catalog: catalog_dir setting with detect, set and show`.

### Task 2: Catalog files: frontmatter, terms, strength, ledger, index, lint

**Files:**
- Modify: `scripts/kinetic/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `show()`, `init_layout()` (Task 1).
- Produces:
  - `read_doc(p: Path) -> tuple[dict, str]` and `write_doc(p: Path, meta: dict, body: str) -> None` (atomic). Raises `CatalogError(f"{p}:{line}: ...")` on missing fences or bad JSON. `CatalogError` subclasses `ValueError`.
  - `load(d: Path) -> dict` returns `{"terms": {term: {...}}, "repos": {repo: meta}, "recipes": {slug: (meta, body)}, "ledger": {key: {...}}}`.
  - `strength(seen: int, of: int) -> str`.
  - `render_recipe(meta: dict) -> str`, `render_index(cat: dict) -> str`, `ledger_lookup(d, keys) -> dict`, `lint(d) -> list[str]`.
  - CLI: `ledger --keys K ...`, `index`, `lint` (exit 1 when lint finds problems; prints `{"problems": [...]}`).
- File shapes (frontmatter JSON):
  - `terms.md`: `{"terms": {"<term>": {"meaning": str, "synonyms": [str], "avoid": [str]}}}`. The body is a generated table.
  - `repos/<repo>.md`: `{"repo", "org", "owns": str, "terms": {"<term>": [<key>...]}, "updated": "YYYY-MM-DD"}`. The count shown is the number of keys. The body is the `owns` line plus a term list with counts.
  - `recipes/<slug>.md`: `{"slug", "title", "when", "parameters": [{"name", "meaning", "examples": [str]}], "terms": [str], "what_for": {"<repo>": [str]}, "sources": [{"key", "prs": [url], "repos": [repo]}], "updated"}`. The body comes from `render_recipe`, in the shape the spec shows in section 2: one `## <repo> (<strength>, <seen> of <of>)` heading per repo, with the repos ordered by `seen` descending, then by name.
  - `ledger.json`: `{"<key>": {"cataloged_at": "YYYY-MM-DD", "recipe": slug|null, "repos": [repo]}}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_doc_round_trip`: `write_doc` then `read_doc` returns the same meta and body.
  - `test_read_doc_bad_frontmatter_names_file_and_line`: a file with `---` then `{bad` raises `CatalogError` whose message has the file path and `:2:`.
  - `test_strength_thresholds`: `strength(1,1)=="seen once"`, `strength(3,3)=="always"`, `strength(2,4)=="usually"`, `strength(3,5)=="usually"`, `strength(2,5)=="sometimes"`, `strength(1,4)=="seen once"`.
  - `test_render_recipe_orders_and_labels_repos`: 3 sources (repo A in all 3, B in 2, C in 1). The headings are `## A (always, 3 of 3)`, `## B (usually, 2 of 3)` and `## C (seen once, 1 of 3)`, in that order, each followed by its `what_for` bullets. The `**When to use:**` line comes first.
  - `test_render_index_lists_recipes_and_repos`: one line per recipe (`slug — title — when — repo (strength)`, comma-separated), and one per repo with its top 5 terms by count (`repo — term (n), ...`).
  - `test_ledger_lookup`: `{"INV-1": {"cataloged": True, ...}, "INV-2": {"cataloged": False}}`.
  - `test_lint_reports_bad_frontmatter`, `test_lint_reports_unknown_term` (a repo term missing from `terms.md`), `test_lint_reports_stale_recipe_body` (the body differs from `render_recipe(meta)`), `test_lint_clean_catalog_is_empty`.
- [ ] **Step 2:** Run the module tests. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** `strength`: `seen == 1` gives `seen once`; else `seen == of` gives `always`; else `2*seen >= of` gives `usually`; else `sometimes`. ("sometimes" is my call, filling the gap the spec's three labels leave. The spec section is updated in Task 5.) `seen` for a repo is the number of `sources` whose `repos` include it, and `of` is `len(sources)`. `render_index` is the only writer of `index.md`.
- [ ] **Step 4:** Run the module tests. Expected: PASS.
- [ ] **Step 5:** Commit `kinetic-repo-catalog: catalog file model, index and lint`.

### Task 3: `apply` an approved change file

**Files:**
- Modify: `scripts/kinetic/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `load`, `write_doc`, `render_recipe`, `render_index` (Task 2).
- Produces: `apply(d: Path, changes: dict, today: str) -> dict` returning `{"written": [relative paths]}`. CLI: `apply --changes F`, which uses `show()` for the folder and exits 1 with the error when unset.
- Change file:
  ```json
  {"deliverables": [{"key": "INV-24468", "repos": ["..."], "prs": ["url"], "recipe": "slug-or-null"}],
   "recipes": [{"slug", "title", "when", "parameters": [...], "terms": [...], "what_for": {"repo": ["line"]}}],
   "repos": [{"repo", "org", "owns": "optional", "terms": {"term": ["INV-24468"]}}],
   "terms": [{"term", "meaning", "synonyms": [], "avoid": []}]}
  ```
- Merge rules: new terms are added to `terms.md`. A recipe in the change creates the file, or updates `title`, `when`, `parameters` and `terms`. Its `what_for` replaces only the repos it names. Each deliverable with a recipe is appended to that recipe's `sources`, with its `key`, `prs` and `repos`. Repo term key lists are unioned, `owns` is replaced only when given, and `updated` is set to `today`. Every deliverable gets a ledger entry. Then `index.md` is regenerated.

- [ ] **Step 1: Write the failing tests:**
  - `test_apply_creates_recipe_profiles_terms_and_ledger`: one deliverable writes the recipe, the repo files, `terms.md`, `ledger.json` and `index.md`, and the recipe repo shows `seen once, 1 of 1`.
  - `test_apply_second_deliverable_raises_counts_and_adds_seen_once_repo`: the second deliverable touches A and B plus a new repo D. A shows `always, 2 of 2` and D shows `seen once, 1 of 2`.
  - `test_apply_keeps_what_for_of_repos_not_named`.
  - `test_apply_refuses_key_already_in_ledger`, `test_apply_refuses_unknown_term`, `test_apply_refuses_unknown_recipe_slug` (a deliverable names a slug that is in neither the change nor the catalog), `test_apply_refuses_when_catalog_file_is_broken`. Each one checks that no file's content or mtime changed.
  - `test_apply_deliverable_without_recipe_goes_to_ledger_only`: `recipe: null` writes the ledger and repo terms, but no recipe.
  - `test_cli_apply_without_catalog_dir_exits_1`.
- [ ] **Step 2:** Run the module tests. Expected: the new tests FAIL.
- [ ] **Step 3: Implement `apply`.** Validate everything against `load(d)` plus the change before any write. Then build every output in memory, write each with `write_doc` or `discover._write`, and write `index.md` last.
- [ ] **Step 4:** Run the module tests. Expected: PASS.
- [ ] **Step 5:** Commit `kinetic-repo-catalog: apply an approved change file`.

### Task 4: `catalog-setup` and `catalog-refresh` skills

**Files:**
- Create: `skills/catalog-setup/SKILL.md`, `skills/catalog-refresh/SKILL.md`
- Modify: `tests/test_skill_text.py:21` (`USER_ONLY_SKILLS` gains `catalog-setup`), `tests/test_install.py:423-425` (`USER_ONLY` gains `catalog-setup`; `SKILL_NAMES` gains both), and any other `SKILL_NAMES` set in `tests/` (`grep -rn SKILL_NAMES tests`).
- Test: `tests/test_skill_text.py`, `tests/test_install.py`

**Interfaces:**
- Consumes: the CLI from Tasks 1 to 3.

- [ ] **Step 1:** Add the names to the test sets. Add `test_catalog_refresh_is_approve_first`, which asserts that the `catalog-refresh` text contains `kinetic catalog apply` and the phrase `writes nothing` (for the "not now" case), and does not contain `git commit`.
- [ ] **Step 2:** Run `PYTHONPATH=scripts python3 -m unittest tests.test_skill_text tests.test_install`. Expected: FAIL (the skills don't exist yet).
- [ ] **Step 3: Write `catalog-setup/SKILL.md`** from spec section 4. Frontmatter: `name`, `description`, `model: sonnet`, `disable-model-invocation: true`, `triggers: [user]`, `argument-hint: "[folder]"`. A folder argument skips the question. Use the harness question tool via `kinetic harness`, as `discover` does.
- [ ] **Step 4: Write `catalog-refresh/SKILL.md`** from spec section 3, steps 1 to 6, with the three inputs `Keys:`, `Query:` and `Run:`. Pin these points:
  - When started by another skill with no catalog set: one line, then return.
  - A query with more than about 20 results asks before it starts.
  - `kinetic catalog ledger` drops keys that are already cataloged.
  - PR search follows the find-ticket-repos lessons: an org-wide `gh search prs "<KEY>" --owner <org>` with an exact-title `--jq` filter, retry once on an empty result, and follow "superseded by / consolidated into".
  - One review message per proposed recipe.
  - The change file goes in the scratch area, then `kinetic catalog apply --changes <file>`.
  - "Not now" writes nothing.
  - No commit, no push.
  - Tracker reads go through the tracker adapter (`trackers/<tracker>.md`). JQL appears only as the Jira example, and only if `test_no_jira_outside_adapters` allows it. Otherwise phrase it as "the tracker's search query".
- [ ] **Step 5:** Run the two test modules. Expected: PASS.
- [ ] **Step 6:** Commit `kinetic-repo-catalog: catalog-setup and catalog-refresh skills`.

### Task 5: `discover`, `cleanup`, docs

**Files:**
- Modify: `skills/discover/SKILL.md` (step 4, plus the network sentence at the top), `skills/cleanup/SKILL.md` (a new step 6), `README.md` (Commands, Configuration with `catalog_dir`, a Catalog section), `GLOSSARY.md`, `docs/specs/kinetic-repo-catalog-design.md` ("sometimes" strength under My calls; section 5 change file replaced by the shape in Task 3)
- Test: `tests/test_skill_text.py`

- [ ] **Step 1: Write the failing tests:**
  - `test_discover_reads_catalog`: the discover text contains `kinetic catalog show`, `index.md`, and the phrase `never skips` (confirm).
  - `test_cleanup_offers_catalog_after_report`: in the cleanup text, `catalog-refresh` appears after `## 5. Report`.
- [ ] **Step 2:** Run `PYTHONPATH=scripts python3 -m unittest tests.test_skill_text`. Expected: FAIL.
- [ ] **Step 3: Edit `discover`** per spec section 6:
  - The catalog becomes the first source in step 4, with the confidence mapping: always is strong, usually is medium, sometimes and seen once are weak, and a terms-only match is medium at most.
  - The reason line names the recipe.
  - The `what_for` lines are copied into `discovery.md`.
  - Step 1 is unchanged.
- [ ] **Step 4: Edit `cleanup`** per spec section 7. A new `## 6. Offer to catalog` step asks once, only when `kinetic catalog show` succeeds and at least one PR is merged. On yes, it follows `catalog-refresh` with `Run: <run_dir>`. State that cleanup is the one skill that invokes another.
- [ ] **Step 5: Glossary and README.** `GLOSSARY.md` gains a `## Catalog` section:
  - **Catalog:** the user-set folder of repo profiles and recipes. Avoid: knowledge base, index.
  - **Recipe:** a kind of change, with its repos and what each is needed for. Avoid: playbook, template.
  - **Deliverable:** a ticket, or an epic with its children, cataloged as one unit. Avoid: task, story.

  `README.md` gets the two commands and the setting. `tests/test_vocabulary.py` must still pass.
- [ ] **Step 6:** Run the full suite. Expected: OK, with the baseline count plus the new tests.
- [ ] **Step 7:** Commit `kinetic-repo-catalog: discover reads the catalog, cleanup offers it`.

### Task 6: Smoke run

**Files:**
- Create: `docs/smoke/catalog.md`

- [ ] **Step 1:** In a temp `HOME`, run `kinetic catalog set --dir <tmp>/catalog --create`, then `apply` three hand-written change files modelled on INV-24468, INV-24150 and INV-24153, then `lint`. Expected: `{"problems": []}`, and an `index.md` listing one recipe.
- [ ] **Step 2:** Record the commands, the outputs, and a manual `/kinetic:catalog-refresh INV-24468` session (if the user runs it) in `docs/smoke/catalog.md`. Mark any step that wasn't run as not run.
- [ ] **Step 3:** Commit `kinetic-repo-catalog: smoke notes`.
