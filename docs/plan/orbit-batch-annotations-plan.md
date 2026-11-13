# Orbit Batches, Source Keys and Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Orbit three general features: Annotations (tool-owned data on a Task), Source Keys (retry-safe identity on `add`), and `orbit batch` (many Task operations, one lock, one commit, all or none).

**Architecture:** Annotations and Source Keys are new frontmatter fields on `TaskFrontmatter`, returned by `task_summary` and shown by `format_detail`. Batch applies operations to one in-memory `Graph` loaded under the exclusive Board lock. It writes nothing until every operation succeeds, then writes each changed Task file atomically and commits once. To keep one implementation per rule, each single command's in-graph logic moves into a new `src/ops.rs`. The single commands and `batch` both call it.

**Tech Stack:** Rust (edition per `Cargo.toml`), clap, serde/serde_json/serde_yaml_ng, the `tests/common` `TestRepo` harness.

**Repository:** run this plan in the Orbit repository (`../orbit`), in a worktree as its `AGENTS.md` requires. It is kept in kinetic's `docs/plan/` only because it was written from kinetic's design doc.

**Spec:** [kinetic-orbit-tracker-design.md](../specs/kinetic-orbit-tracker-design.md), section "Part 1: Orbit changes". Read only Part 1 and "Vocabulary". Part 1 must stay free of kinetic vocabulary.

## Global Constraints

- No kinetic vocabulary (kinetic, ticket, slice, blocker, run) anywhere in Orbit code, help, docs, ADRs, tests or examples. Example owners are `ci` and `planner`. Example Source Keys look like `planner:plan-7:step-3`.
- Do not use these words for the new concepts: namespace, store, client, blocker, metadata, custom field, extra.
- New glossary terms, exactly: **Batch**, **Source Key**, **Annotation** (with its **owner**).
- Commands, exactly: `orbit batch --file <path|->` with `--dry-run`; `orbit annotation set <id> <owner> --json <object>`; `orbit annotation remove <id> <owner>`; `orbit add --source-key <key>`.
- Frontmatter keys, exactly: `annotations` (map owner to JSON object) and `source_key` (string).
- An owner is a lowercase slug: `^[a-z0-9][a-z0-9-]*$`, at most 40 characters.
- An Annotation value is a JSON object and at most 8192 bytes when serialized compactly.
- A Source Key is 1 to 200 printable non-whitespace ASCII characters and unique per Board.
- Annotations never affect Ready, Blocked, Claim eligibility or Status, and are never pushed to or pulled from a Remote Tracker.
- `orbit export` `schema_version` goes from 2 to 3.
- Every new CLI command has an MCP tool (ADR 0004 parity).
- Docs travel with each commit: `docs/GLOSSARY.md`, `docs/SPEC.md`, `docs/commands.md`, CLI `--help` in `src/help.rs`, `CHANGELOG.md`, and the managed AGENTS block template in `src/setup.rs` when agent workflow text changes.

## Review Focus

- **A crash between file writes inside a Batch.** A reasonable person expects re-running the same Batch to finish the job without duplicate Tasks or errors. Re-running `add` with the same Source Key, `label`, `depend`, `annotate`, a `claim` by the current holder, and `done` on a Done Task must all succeed as no-ops. Pinned by `batch_rerun_after_partial_apply_converges` (Task 6).
- **A Batch that refers to a Source Key created earlier in the same Batch,** for example a SubTask whose parent is `key:...` of an `add` two operations earlier. Expected to resolve in order. Pinned by `batch_resolves_keys_created_earlier_in_the_batch` (Task 6).
- **Annotations on a Task that a `slug migrate` rewrites.** Expected to survive unchanged. Pinned by `annotations_survive_slug_migration` (Task 1).
- **An older Orbit reading a Board with `annotations`.** It keeps them in `extra` and writes them back untouched (today's flatten behavior). Pinned by `unknown_frontmatter_round_trip_keeps_annotations` (Task 1).
- **Two Tasks claiming the same Source Key** after a hand edit or a merge of two Board branches. `orbit doctor` reports `DUPLICATE_SOURCE_KEY`, and `add` with that key refuses with the same code instead of picking one. Pinned by `duplicate_source_key_is_reported` (Task 3).

---

### Task 1: Annotations in the Task model and JSON output

**Files:**
- Modify: `src/task.rs` (`RawFrontmatter`, `TaskFrontmatter`, both `From` impls, new validation fn)
- Modify: `src/graph.rs` (`task_summary` adds `"annotations"`)
- Modify: `src/commands/render.rs` (`format_detail` prints one `annotation <owner>: <compact json>` line per owner)
- Modify: `src/commands/query.rs:397` (`schema_version` 3)
- Modify: `src/doctor.rs` (report `INVALID_ANNOTATION`)
- Modify: `src/error.rs` (add `INVALID_ANNOTATION`)
- Modify: `src/remote*` adapters only if a test shows Annotations leaking. They must not be mapped fields.
- Test: `tests/annotations.rs` (new)

**Interfaces:**
- Produces: `TaskFrontmatter.annotations: BTreeMap<String, serde_json::Value>` (empty map is omitted when serialized); `pub fn validate_annotation(owner: &str, value: &serde_json::Value) -> Result<()>` in `src/task.rs`; constant `code::INVALID_ANNOTATION`.

- [ ] **Step 1: Write the failing tests** in `tests/annotations.rs`. Write Annotations by editing the Task file in the test (the CLI arrives in Task 2):
  - `annotations_appear_in_show_list_and_export`: after adding `annotations: {ci: {passed: true}}` to a Task file, `show --json` `data.annotations == {"ci": {"passed": true}}`, the same in `list --json` `data.tasks[0].annotations`, `export --json` `data.schema_version == 3`, and the Task's export entry has the same `annotations`.
  - `task_without_annotations_reports_empty_object`: `show --json` `data.annotations == {}`.
  - `human_show_prints_one_line_per_owner`: `orbit show <id>` stdout contains `annotation ci: {"passed":true}`.
  - `annotations_do_not_affect_ready`: a Task with an Annotation is Ready exactly as without one.
  - `doctor_reports_non_object_annotation`: an Annotation whose value is `[1]` makes `doctor --json` report an issue with code `INVALID_ANNOTATION`.
  - `annotations_survive_slug_migration`: after `orbit slug migrate` to a new slug, the migrated Task's `annotations` are unchanged.
  - `unknown_frontmatter_round_trip_keeps_annotations`: a `label add` on an annotated Task keeps the `annotations` block byte-for-byte in the file.

- [ ] **Step 2: Run them and confirm they fail**

Run: `cargo test --test annotations`
Expected: FAIL (`annotations` missing from JSON, `schema_version` is 2).

- [ ] **Step 3: Implement.** Add `annotations` to `RawFrontmatter` with `#[serde(default, skip_serializing_if = "BTreeMap::is_empty")]` before the `extra` flatten, so it is no longer swallowed by `extra`. Carry it through both `From` impls. Store values as `serde_json::Value` (convert from YAML on read). Implement `validate_annotation` with the owner regex, the object check and the 8192-byte cap from Global Constraints. Doctor calls it for every stored Annotation.

- [ ] **Step 4: Run the new tests and the whole suite**

Run: `cargo test`
Expected: PASS, including existing `tests/export.rs` after its expected `schema_version` is updated to 3.

- [ ] **Step 5: Docs.** `docs/GLOSSARY.md` gets the **Annotation** entry worded as in the spec, with _Avoid_: metadata, custom field, namespace, extra. `docs/SPEC.md` documents the `annotations` frontmatter key and export `schema_version` 3. `src/help.rs` export help mentions the bump. Add a `CHANGELOG.md` entry.

- [ ] **Step 6: Commit**

```bash
git add src/task.rs src/graph.rs src/commands/render.rs src/commands/query.rs src/doctor.rs src/error.rs tests/annotations.rs tests/export.rs docs/GLOSSARY.md docs/SPEC.md src/help.rs CHANGELOG.md
git commit -m "feat(task): store and show Annotations; export schema_version 3"
```

### Task 2: `orbit annotation set|remove` and its MCP tool

**Files:**
- Modify: `src/cli.rs` (`Command::Annotation(AnnotationArgs)`, `AnnotationCommand::{Set, Remove}`)
- Create: `src/ops.rs` with the first op, `annotate`
- Modify: `src/lib.rs` (`mod ops;`), `src/commands/mod.rs` (dispatch under `with_task_board(.., true, ..)`), new `src/commands/annotation.rs`
- Modify: `src/mcp.rs` (tool `annotate`, and `tool_list_contains_task_tools` count 14 to 15)
- Test: `tests/annotations.rs`, `src/mcp.rs` unit test

**Interfaces:**
- Consumes: `validate_annotation` (Task 1).
- Produces: `pub fn annotate(graph: &mut Graph, id: &str, owner: &str, value: Option<serde_json::Value>, now: DateTime<Utc>) -> Result<bool>` in `src/ops.rs`, where `None` removes and the result is whether the Task changed. JSON output of both commands: `{"id", "owner", "annotation": <object|null>, "changed": bool}`.

- [ ] **Step 1: Write the failing tests**
  - `annotation_set_replaces_the_owner_value`: `annotation set <id> ci --json '{"a":1}'`, then `--json '{"b":2}'`. `show --json` `data.annotations == {"ci": {"b": 2}}`.
  - `annotation_set_keeps_other_owners`: setting `planner` leaves `ci` untouched.
  - `annotation_remove_deletes_the_owner`: remove `ci` and `annotations == {}`. Removing again returns `ok` with `changed: false`.
  - `annotation_set_rejects_bad_input`: owner `CI`, a value `[1]` and a 9000-byte object each fail with `error.code == "INVALID_ANNOTATION"`, and the Task file is unchanged.
  - `annotation_set_makes_one_commit`: the Board branch has exactly one new commit, with message `orbit: annotate <id> ci`.
  - MCP unit test: `tool_list_contains_task_tools` expects 15 tools, including `annotate`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `cargo test --test annotations && cargo test --lib mcp`
Expected: FAIL (unrecognized subcommand `annotation`, 14 tools).

- [ ] **Step 3: Implement** `ops::annotate`. The command loads the Graph, calls the op, and when it changed saves with `mutation::save(board, &task, "orbit: annotate <id> <owner>")`. The MCP tool `annotate` takes `id`, `owner` and `value` (object or null) and spawns `orbit annotation set|remove ... --json`.

- [ ] **Step 4: Run the tests**

Run: `cargo test`
Expected: PASS

- [ ] **Step 5: Docs.** `docs/commands.md` gets a section "`orbit annotation` — attach tool-owned data" under "Create and shape work". Add `src/help.rs` long help with one `ci` example and a `CHANGELOG.md` entry.

- [ ] **Step 6: Commit**

```bash
git add src/cli.rs src/ops.rs src/lib.rs src/commands/mod.rs src/commands/annotation.rs src/mcp.rs tests/annotations.rs docs/commands.md src/help.rs CHANGELOG.md
git commit -m "feat(cli): orbit annotation set and remove"
```

### Task 3: Source Keys on `add`

**Files:**
- Modify: `src/task.rs` (`source_key: Option<String>` in `RawFrontmatter` and `TaskFrontmatter`, `validate_source_key`)
- Modify: `src/graph.rs` (`find_by_source_key`, duplicate check in `validate`, `"source_key"` in `task_summary`)
- Modify: `src/cli.rs` (`AddArgs.source_key: Option<String>`, flag `--source-key`)
- Modify: `src/ops.rs` (move `cmd_add`'s in-graph logic into `ops::add`), `src/commands/crud.rs` (`cmd_add` calls it)
- Modify: `src/error.rs` (`INVALID_SOURCE_KEY`, `DUPLICATE_SOURCE_KEY`)
- Test: `tests/source_keys.rs` (new)

**Interfaces:**
- Produces: `pub struct NewTask { title, priority, task_type, labels, depends_on, parent, waiting_on, area, verification, repo, body, source_key, annotations }` and `pub fn add(graph: &mut Graph, board: &Board, new: NewTask, now: DateTime<Utc>) -> Result<AddOutcome>` in `src/ops.rs`, where `pub struct AddOutcome { pub id: String, pub matched: bool }`. `pub fn find_by_source_key(&self, key: &str) -> Result<Option<&Task>>` on `Graph`, which errors with `DUPLICATE_SOURCE_KEY` when two Tasks carry the key.
- `add --json` output gains `data.source_key` and `meta.matched` (true when an existing Task was returned).

- [ ] **Step 1: Write the failing tests** in `tests/source_keys.rs`:
  - `add_with_source_key_stores_and_returns_it`: `show --json` `data.source_key == "planner:plan-7:step-3"`.
  - `add_with_existing_source_key_returns_the_same_task`: a second `add "Other title" --source-key planner:plan-7:step-3 --json` returns the first Task's ID with `meta.matched == true`. The Board still has one Task, and no new commit was made.
  - `source_key_must_be_valid`: an empty key, a key with a space and a 201-character key fail with `INVALID_SOURCE_KEY`.
  - `duplicate_source_key_is_reported`: two Task files edited to share a key make `doctor --json` report `DUPLICATE_SOURCE_KEY`, and `add --source-key <that key>` fails with the same code.
  - All existing `tests/cli.rs` `add` tests still pass (behavior with no key is unchanged).

- [ ] **Step 2: Run and confirm failure**

Run: `cargo test --test source_keys`
Expected: FAIL (unexpected argument `--source-key`).

- [ ] **Step 3: Implement.** Moving `cmd_add` into `ops::add` must not change any validation or message: `cmd_add` becomes argument parsing, then `ops::add`, then `mutation::create_task`, `mutation::commit` and output. When `source_key` matches an existing Task, `ops::add` returns `matched: true` without validating the other fields, and the command skips the write and commit.

- [ ] **Step 4: Run all tests**

Run: `cargo test`
Expected: PASS

- [ ] **Step 5: Docs.** Add the GLOSSARY entry **Source Key** as in the spec. Document `--source-key` in `docs/commands.md` under `orbit add`, and the `source_key` key in `docs/SPEC.md`. Update the `add` help and `CHANGELOG.md`.

- [ ] **Step 6: Commit**

```bash
git add src/task.rs src/graph.rs src/cli.rs src/ops.rs src/commands/crud.rs src/error.rs tests/source_keys.rs docs/GLOSSARY.md docs/commands.md docs/SPEC.md src/help.rs CHANGELOG.md
git commit -m "feat(add): Source Keys make add retry-safe"
```

### Task 4: Move shaping operations into `src/ops.rs`

A refactor with no behavior change, so Batch can reuse one implementation of each rule.

**Files:**
- Modify: `src/ops.rs`, `src/commands/crud.rs` (`cmd_update`), `src/commands/relations.rs` (`mutate_labels`, `cmd_depend`, `cmd_undepend`)
- Test: existing `tests/cli.rs`, `tests/labels_comments.rs`, `tests/properties.rs`, `tests/subtasks.rs`

**Interfaces:**
- Produces, all in `src/ops.rs`, each returning `Result<bool>` (whether the Task changed) and never writing files:
  - `pub fn update(graph: &mut Graph, board: &Board, id: &str, change: TaskUpdate, now: DateTime<Utc>) -> Result<bool>` with `pub struct TaskUpdate { title: Option<String>, body: Option<String>, priority: Option<u8>, task_type: Option<TaskType>, waiting_on: FieldUpdate<String> }` (reuse the existing `FieldUpdate`).
  - `pub fn label(graph: &mut Graph, id: &str, add: &[String], remove: &[String], now: DateTime<Utc>) -> Result<bool>`
  - `pub fn depend(graph: &mut Graph, id: &str, on: &str, now: DateTime<Utc>) -> Result<bool>`
  - `pub fn undepend(graph: &mut Graph, id: &str, on: &str, now: DateTime<Utc>) -> Result<bool>`

- [ ] **Step 1: Run the suite as the baseline**

Run: `cargo test`
Expected: PASS (record the count).

- [ ] **Step 2: Move the in-graph logic** of each command into its op, keeping every error code and message. Each command becomes load, op, `mutation::save` when changed, output. Batch reruns need `depend` on an edge that already exists to succeed unchanged. If `orbit depend` errors on a repeated edge today, `ops::depend` returns `Ok(false)` for it, and the command keeps reporting success with `changed: false`. Pin this with `depend_existing_edge_is_unchanged` in `tests/cli.rs`.

- [ ] **Step 3: Run the suite**

Run: `cargo test`
Expected: PASS with the same count as Step 1.

- [ ] **Step 4: Commit**

```bash
git add src/ops.rs src/commands/crud.rs src/commands/relations.rs
git commit -m "refactor(ops): shaping operations work on an in-memory Graph"
```

### Task 5: Move lifecycle operations and comments into `src/ops.rs`

**Files:**
- Modify: `src/ops.rs`, `src/mutation.rs` (`execute_in`, `finish`, `reopen` delegate to ops for the in-graph part), `src/commands/lifecycle.rs`, `src/commands/relations.rs` (`cmd_comment_add`)
- Test: existing `tests/checkpoints.rs`, `tests/concurrency.rs`, `tests/subtasks.rs`, `tests/labels_comments.rs`, and the `transition.rs` unit matrices

**Interfaces:**
- Produces in `src/ops.rs`: `claim(graph, board, id, by: &str, steal: bool, now) -> Result<bool>`, `heartbeat(graph, board, id, by, now) -> Result<bool>`, `release(graph, id, by: Option<&str>, force: bool, now) -> Result<bool>`, `done(graph, id, by, force: bool, now) -> Result<bool>`, `cancel(graph, id, by, force, now) -> Result<bool>`, `reopen(graph, id, force, now) -> Result<bool>`. Comments stay sidecar files: `pub fn comment(board: &Board, id: &str, by: &str, body: &str, now) -> Result<PendingComment>` returns the rendered comment without writing it, and `pub fn write_comment(board: &Board, pending: &PendingComment) -> Result<()>` writes it.
- Same-holder rule (used by Batch reruns): `claim` by the current holder of a live or Stale Claim renews the Lease and returns `Ok(true)` instead of `ALREADY_CLAIMED`. This is the only behavior change in this task.

- [ ] **Step 1: Write the failing test** in `tests/checkpoints.rs`: `claim_by_current_holder_renews_the_lease` asserts that a second `claim <id> --by a --json` is `ok` with a later `lease_until`, and that a claim by `b` still fails with `ALREADY_CLAIMED`.

- [ ] **Step 2: Run and confirm failure**

Run: `cargo test --test checkpoints claim_by_current_holder_renews_the_lease`
Expected: FAIL with `ALREADY_CLAIMED`.

- [ ] **Step 3: Move the in-graph logic** into the ops, then add the same-holder rule in `ops::claim`.

- [ ] **Step 4: Run the suite**

Run: `cargo test`
Expected: PASS (all earlier tests plus the new one).

- [ ] **Step 5: Docs.** Note the same-holder renewal under `orbit claim` in `docs/commands.md` and `docs/SPEC.md`, and in `CHANGELOG.md`.

- [ ] **Step 6: Commit**

```bash
git add src/ops.rs src/mutation.rs src/commands/lifecycle.rs src/commands/relations.rs tests/checkpoints.rs docs/commands.md docs/SPEC.md CHANGELOG.md
git commit -m "refactor(ops): lifecycle operations on an in-memory Graph; same-holder claim renews"
```

### Task 6: `orbit batch`

**Files:**
- Create: `src/commands/batch.rs`, `docs/adr/0020-batches-source-keys-and-annotations.md`
- Modify: `src/cli.rs` (`Command::Batch(BatchArgs { file: String, dry_run: bool, by: Option<String> })`), `src/commands/mod.rs` (dispatch under `with_task_board(.., true, ..)`), `src/mcp.rs` (tool `batch`, count 16), `src/error.rs` (`INVALID_BATCH`)
- Test: `tests/batch.rs` (new)

**Interfaces:**
- Consumes: every op from Tasks 2 to 5, and `Graph::find_by_source_key`.
- Input (file or stdin), exactly:

```json
{"operations": [
  {"op": "add", "key": "planner:plan-7:epic", "title": "Plan 7", "type": "epic"},
  {"op": "add", "key": "planner:plan-7:step-1", "title": "Step 1", "parent": "key:planner:plan-7:epic",
   "labels": ["hold-me"], "depends_on": [], "body": "...", "priority": 2, "repo": null,
   "annotations": {"planner": {"order": 1}}},
  {"op": "label", "id": "key:planner:plan-7:step-1", "add": [], "remove": ["hold-me"]},
  {"op": "claim", "id": "key:planner:plan-7:step-1", "by": "planner-7"},
  {"op": "update", "id": "<task id>", "waiting_on": "a decision", "clear_waiting": false},
  {"op": "depend", "id": "...", "on": "..."}, {"op": "undepend", "id": "...", "on": "..."},
  {"op": "heartbeat", "id": "...", "by": "..."}, {"op": "release", "id": "...", "by": "...", "force": false},
  {"op": "done", "id": "...", "by": "...", "comment": "optional", "force": false},
  {"op": "cancel", "id": "...", "by": "...", "force": false}, {"op": "reopen", "id": "...", "force": false},
  {"op": "comment", "id": "...", "by": "...", "body": "..."},
  {"op": "annotate", "id": "...", "owner": "planner", "value": {"order": 2}}
]}
```

  A reference (`id`, `on`, `parent`, `depends_on` entries) is a Task ID, or `key:` followed by a Source Key that already exists on the Board or was added earlier in the Batch. `by` defaults to `--by`, then `ORBIT_AGENT`, then `USER`, as in single commands. Unknown fields fail with `INVALID_BATCH`.
- Output `data`: `{"keys": {"<source key>": "<task id>"}, "results": [{"index": 0, "op": "add", "id": "...", "changed": true, "matched": false}], "commit": "<sha>|null", "dry_run": false}`.
- Error: the failing operation's own error code, with `error.details.index` and `error.details.op` added. Malformed input fails with `INVALID_BATCH`.

- [ ] **Step 1: Write the failing tests** in `tests/batch.rs`:
  - `batch_creates_parent_subtasks_and_dependencies_in_one_commit`: the first two operations above plus a second SubTask that `depends_on` the first by key. Afterwards three Tasks exist, the dependency is stored as a Task ID, `data.keys` has three entries, and the Board branch has exactly one new commit.
  - `batch_resolves_keys_created_earlier_in_the_batch`: a `parent` given as `key:` resolves to the new epic's ID.
  - `batch_failure_writes_nothing`: operation 2 depends on a missing Task. The error code is `NOT_FOUND`, `details.index == 2` and `details.op == "depend"`. The Board's task files and commit count are unchanged.
  - `batch_dry_run_validates_without_writing`: `--dry-run` returns the full result with `commit: null` and `dry_run: true`, and nothing changes.
  - `batch_remove_hold_label_and_claim_together`: a Task held by `needs-triage` is unheld and claimed in one Batch. A competing `orbit ready --claim` run before it sees no Ready Task.
  - `batch_rerun_after_partial_apply_converges`: simulate a crash partway through a Batch by applying only its first operations by hand (`orbit add --source-key ...` for the epic, then `label add` for one Task). Running the full Batch then succeeds, and the Board ends with exactly the Tasks, edges, Labels and Annotations of one clean run.
  - `batch_rejects_unknown_fields`: `{"op": "add", "titel": "x"}` fails with `INVALID_BATCH`.
  - `batch_heartbeat_only_does_not_commit`: a Batch of only `heartbeat` operations reports `commit: null` (like `orbit heartbeat`).
  - MCP unit test: 16 tools, including `batch`.

- [ ] **Step 2: Run and confirm failure**

Run: `cargo test --test batch`
Expected: FAIL (unrecognized subcommand `batch`).

- [ ] **Step 3: Implement** `cmd_batch` in `src/commands/batch.rs`: parse with `serde(deny_unknown_fields)`, load the Graph once, keep a `keys: BTreeMap<String, String>`, and apply each operation through `src/ops.rs` in order, collecting changed IDs and pending comments. On the first error, return it with `index` and `op` and write nothing. On success, unless `--dry-run`: `create_task` for new Tasks, `write_task` for changed ones, `write_comment` for comments, then one `mutation::commit(board, "orbit: batch <n> operations")`. Skip the commit when only Leases changed.

- [ ] **Step 4: Run all tests**

Run: `cargo test`
Expected: PASS

- [ ] **Step 5: Docs.** ADR 0020 records the decisions:
  - Batch, Source Keys and Annotations.
  - The `batch` name, chosen over `apply` because of the existing `--apply` flags.
  - Validate in memory, then write and commit.
  - A crash between writes is covered by reruns being idempotent.
  - Annotations are never synced to Remote Trackers.

  Also:
  - GLOSSARY **Batch** entry.
  - `docs/commands.md`: a section "`orbit batch` — apply many changes at once" under "Create and shape work", with the input and output shapes.
  - `docs/SPEC.md`: the same contract.
  - `src/help.rs`: long help with the `planner` example.
  - The managed AGENTS block in `src/setup.rs`: add one line, "`orbit batch --file plan.json` applies many changes in one commit, all or none; `--source-key` makes retries safe."
  - `CHANGELOG.md`.

- [ ] **Step 6: Commit**

```bash
git add src/commands/batch.rs src/cli.rs src/commands/mod.rs src/mcp.rs src/error.rs tests/batch.rs docs/adr/0020-batches-source-keys-and-annotations.md docs/GLOSSARY.md docs/commands.md docs/SPEC.md src/help.rs src/setup.rs CHANGELOG.md
git commit -m "feat(batch): orbit batch applies many operations in one commit, all or none"
```

### Task 7: Release

- [ ] **Step 1: Check docs for leaked vocabulary**

Run: `grep -rniE "kinetic|\bticket|\bslice|namespace|\bblocker" docs src tests README.md AGENTS.md | grep -v "docs/brainstorming.md\|docs/spec_alpha.md"`
Expected: no new lines from this plan's changes. Compare with `git diff main --stat` and the same grep on `main`.

- [ ] **Step 2: Release** following `docs/RELEASING.md`, as the next minor version (0.11.0). Batch, Annotations and the new export `schema_version` are additive.

- [ ] **Step 3: Record the version** for kinetic: the kinetic plan's `ORBIT_MIN_VERSION` is this release's version.
