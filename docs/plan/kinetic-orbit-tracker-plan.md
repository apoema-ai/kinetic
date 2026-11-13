# Kinetic Orbit Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `orbit` tracker: a run's tickets live as Tasks on an Orbit Board, behind a ticket store interface, while every other tracker keeps working exactly as today.

**Architecture:** A new `ticket_store` module defines the interface and the local ticket store (today's `state.json` behavior). `orbit_store` is the only Python module that knows Orbit. `state.load` fills `state["tickets"]` from the run's ticket store, and `state._mutate` sends ticket changes back through it. So `board`, `frontier`, `gitops`, `graph`, `next_step` and `status` keep reading `state["tickets"]` and need no change. Liveness rides on the existing PostToolUse hooks (`record_edit.py`, `claim_run.py`), so no harness installer changes.

**Tech Stack:** Python 3 standard library only, `unittest` (`PYTHONPATH=scripts python3 -m unittest discover -s tests -v`), the `orbit` CLI (0.11.0 or later) called with `--json`.

**Spec:** [kinetic-orbit-tracker-design.md](../specs/kinetic-orbit-tracker-design.md), Part 2 and Mapping. **Depends on:** [orbit-batch-annotations-plan.md](orbit-batch-annotations-plan.md) being released. Task 1 and Task 2 can start before that release.

## Global Constraints

- The word `orbit` (any case) appears only in: `scripts/kinetic/orbit_store.py`, `trackers/orbit.md`, the `TRACKERS` tuple and `REQUIRED` map in `scripts/kinetic/tracker.py`, `skills/init/SKILL.md`, `README.md`, `GLOSSARY.md`, `docs/`, and tests. Task 6 adds a test that enforces this.
- Every tracker except `orbit` uses the local ticket store, and its behavior and `state.json` contents are unchanged. All existing tests pass unmodified.
- Constants in `orbit_store.py`: `ORBIT_MIN_VERSION = (0, 11, 0)`, `ORBIT_SCHEMA_VERSION = 3`, `ANNOTATION_OWNER = "kinetic"`, `LOCK_RETRIES = (0.2, 0.4, 0.8)` seconds, retried only on `error.code == "LOCKED"`.
- Names, as defaults in `trackers/orbit.md`'s names block and overridable through `tracker_names`: `hold` = `kinetic`, `run` = `kinetic-run-<run id>`, `kind.human` = `ready-for-human`, `ships_with` = `ships-with-<group>`.
- Claim holder `kinetic-<run id>`. Source Key `kinetic:<run id>:<provisional id>`.
- Touch at most once per 300 seconds per ticket. A failed touch never fails or blocks a hook.
- Kinetic never edits Orbit files. Every Orbit change is one `orbit batch` call with `--dir <anchor>`.
- With the Orbit ticket store, `state.json` holds no `tickets` entries (an empty `{}` stays for older readers).
- Vocabulary: "ticket store" for the interface, "tracker adapter" for `trackers/*.md`. Never "adapter" unqualified, "backend" or "board" for the interface.

## Review Focus

- **The Orbit Board is unreachable mid-run** (binary removed, Board deleted, lock timeout after retries). A person expects a clear error naming the fix and an unchanged `state.json`, never a half-written state. Pinned by `test_orbit_failure_leaves_state_json_untouched` (Task 3).
- **A run started before this change** has no `ticket_store` key in `state.json`. Expected to load as local, exactly as today. Pinned by `test_state_without_ticket_store_key_loads_as_local` (Task 1).
- **The same ticket is changed twice in one `_mutate`,** or changed and then changed back. Expected: at most one Batch, and none when the end state equals the start. Pinned by `test_no_op_mutation_sends_no_batch` (Task 3).
- **Publish is re-run after a crash** that happened after Orbit committed but before the staged file was removed. Expected: no duplicate Tasks, ids rewritten, staged files gone. Pinned by `test_publish_twice_is_safe` (Task 4).
- **A person runs `orbit done` on an agent ticket** (not a human one). Kinetic must not treat that as its own done, because it has no passing verify. Expected: the ticket is shown with status `needs_decision` and a note naming the outside change. Pinned by `test_outside_done_on_agent_ticket_needs_decision` (Task 3).

---

### Task 1: Ticket store interface and the local ticket store

**Files:**
- Create: `scripts/kinetic/ticket_store.py`
- Modify: `scripts/kinetic/state.py` (`init`, `load`, `save`, `_mutate`)
- Test: `tests/test_ticket_store.py` (new)

**Interfaces:**
- Produces in `ticket_store.py`:
  - `class TicketStore` (a Protocol) with `read(run_dir, st: dict) -> dict[str, dict]`, `write(run_dir, st: dict, before: dict, after: dict) -> None`, `stage_path(run_dir) -> Path | None`, `publish(run_dir, st: dict) -> dict[str, str]` (provisional id to final id), `touch(run_dir, st, ticket_id: str) -> None`, `health(settings: Path) -> list[dict]` (rows shaped like `doctor._r`). Comments are not part of it. They stay a tracker adapter operation.
  - `class LocalTicketStore` implementing it: `read` returns `st["tickets"]`, `write` is a no-op (the tickets are saved with `state.json`), `stage_path` is `None`, `publish` returns the identity map, `touch` is a no-op, `health` returns `[]`.
  - `def store_for(record: dict) -> TicketStore`. Kind `local` gives `LocalTicketStore`. Any other kind `k` imports `kinetic.<k>_store` and calls its `make(record["config"])`. `def for_state(st: dict) -> TicketStore` is `store_for(st.get("ticket_store", {"kind": "local"}))`. `def for_tracker(tracker: str) -> dict` returns `{"kind": tracker, "config": {}}` when `importlib.util.find_spec(f"kinetic.{tracker}_store")` exists, else `{"kind": "local"}`. This module never names a specific non-local store.
- `state.init(run_dir, lane, ref, force=False, ticket_store: dict | None = None)` records `ticket_store` (default `{"kind": "local"}`). `state.load` returns `st` with `st["tickets"] = for_state(st).read(run_dir, st)`. `state._mutate` copies the tickets before `fn`, calls `for_state(st).write(run_dir, st, before, after)`, then saves `state.json`, without tickets for a non-local store. Validation stays where it is.

- [ ] **Step 1: Write the failing tests** in `tests/test_ticket_store.py`:
  - `class TicketStoreContract` (a mixin) with `make_run()` overridden per store, and these tests: `test_set_ticket_then_load_round_trips` (every field in `state.ticket_defaults()` plus `worktree`, `produces` and `consumes` round-trips), `test_set_ticket_status_done_requires_verify` (same refusal text as today), `test_human_done` (status `done`, `done_by == "human"`), `test_frontier_ready_matches` (the fixture graph gives the same `frontier.ready` list).
  - `class LocalContractTest(TicketStoreContract, unittest.TestCase)`.
  - `test_state_without_ticket_store_key_loads_as_local`: a `state.json` written by the current code, with no `ticket_store`, loads and mutates exactly as before.

- [ ] **Step 2: Run and confirm failure**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_ticket_store -v`
Expected: FAIL with `ModuleNotFoundError: kinetic.ticket_store`.

- [ ] **Step 3: Implement** `ticket_store.py` and the `state.py` changes.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
Expected: PASS, with every existing test unchanged.

- [ ] **Step 5: Commit**

```bash
git add scripts/kinetic/ticket_store.py scripts/kinetic/state.py tests/test_ticket_store.py
git commit -m "kinetic-orbit: ticket store interface with the local ticket store"
```

### Task 2: Register the `orbit` tracker and its tracker adapter

**Files:**
- Modify: `scripts/kinetic/tracker.py` (`TRACKERS`, `REQUIRED["orbit"] = []`)
- Create: `trackers/orbit.md`
- Modify: `skills/init/SKILL.md` (offer `orbit` when `orbit --version` succeeds and `orbit list --json` finds a Board from the current directory), `skills/decompose/SKILL.md` (step 4 gets one generic sentence: "When the tracker adapter says it publishes staged tickets, follow the Local steps; kinetic publishes them when the breakdown gate is approved.")
- Modify: `skills/run/SKILL.md` (`kinetic state init` passes `--ticket-store "$(kinetic tracker store-record)"`)
- Test: `tests/test_tracker.py`, `tests/test_skill_text.py`

**Interfaces:**
- Produces: `trackers/orbit.md` with a "## Default names" JSON block that has every role in `tracker.ROLES` plus `hold` and `run`. Values: `kind.agent` = `""` (no Label), `kind.human` = `ready-for-human`, `edge.*` = `""` (edge types live in the Annotation), `after`, `related` = `""`, `ships_with` = `ships-with-<group>`, `status.todo` = `todo`, `status.running` = `in_progress`, `status.blocked` = `in_progress`, `status.done` = `done`, `status.merged` = `done`, `hold` = `kinetic`, `run` = `kinetic-run-<run id>`. Its operations section says that every ticket operation is done by `kinetic state` commands through the ticket store. The exceptions: "fetch" is `orbit show <id> --json`, "comment" is `orbit comment add <id> --by kinetic-<run id> --body-file -`, and "ticket reference" is the Task ID. It also states "publishes staged tickets".
- Produces: `kinetic tracker store-record` prints `json.dumps(ticket_store.for_tracker(resolve()["tracker"]))`. Until Task 3 adds `orbit_store.py`, `orbit` gives `{"kind": "local"}`.
- Produces: `kinetic state init ... --ticket-store <json>` passes the record to `state.init`.

- [ ] **Step 1: Write the failing tests:**
  - `test_tracker.py::test_orbit_resolves_with_defaults`: settings `{"tracker": "orbit"}` resolve with `names["hold"] == "kinetic"` and `names["kind"]["human"] == "ready-for-human"`.
  - `test_orbit_names_override`: `tracker_names: {"hold": "held-by-run"}` wins.
  - `test_store_record_for_local_trackers`: `github`, `jira`, `linear`, `local` and `other` each give `{"kind": "local"}`.
  - `test_skill_text.py`: the decompose skill contains the generic publish sentence and does not contain `orbit`.

- [ ] **Step 2: Run and confirm failure**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_tracker tests.test_skill_text -v`
Expected: FAIL (`unknown tracker 'orbit'`).

- [ ] **Step 3: Implement** the registry entry, the tracker adapter file, the `store-record` and `comment` subcommands, and the skill text.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/kinetic/tracker.py scripts/kinetic/state.py trackers/orbit.md skills/init/SKILL.md skills/decompose/SKILL.md skills/run/SKILL.md tests/test_tracker.py tests/test_skill_text.py
git commit -m "kinetic-orbit: register the orbit tracker adapter"
```

### Task 3: The Orbit ticket store: read and write published tickets

**Files:**
- Create: `scripts/kinetic/orbit_store.py`
- No change to `ticket_store.py`: `store_for` finds `orbit_store.py` by its name. Importing it never calls the binary, so a missing `orbit` never breaks local runs.
- Test: `tests/test_orbit_store.py` (new), `tests/test_ticket_store.py` (`OrbitContractTest`)

**Interfaces:**
- Consumes: `TicketStore` (Task 1), names from `tracker.resolve()` (Task 2), `orbit batch` and `orbit list --json` (Orbit plan).
- Produces in `orbit_store.py`:
  - `def make(config: dict) -> OrbitTicketStore`, which `ticket_store.store_for` calls.
  - `class OrbitTicketStore` implementing `TicketStore`. `config` keys: `anchor` (absolute path passed as `--dir`, set on first use from the `orbit_dir` setting, else the first repo in `st["repos"]`, then saved in `st["ticket_store"]["config"]`).
  - `def to_ticket(task: dict, names: dict) -> dict` maps one `orbit list --json` Task to a kinetic ticket: the Annotation `kinetic` supplies every field, and the Task ID becomes the key.
  - `def derive(ticket: dict, run_id: str, names: dict) -> dict` returns `{"status": <orbit status>, "claim": "kinetic-<run id>" | None, "waiting_on": str | None, "labels": set[str]}` per the Status table in the spec.
  - `def ops_for(before: dict, after: dict, run_id: str, names: dict) -> list[dict]` returns the `orbit batch` operations that move Orbit from `derive(before)` to `derive(after)`, plus one `annotate` with the full ticket. It returns `[]` when nothing changed.
  - `def call(anchor: str, args: list[str], stdin: str | None = None) -> dict` runs `orbit --dir <anchor> <args> --json`, retries per `LOCK_RETRIES` on `LOCKED`, and raises `OrbitStoreError(code, message, fix)` on any other error.
- `read` makes one `orbit list --json --include-closed --label <names.run>` call. It also reconciles outside changes in one Batch:
  - A human ticket that is Done in Orbit while its Annotation still says `todo` is recorded as `done` with `done_by: human`.
  - An agent ticket that is Done in Orbit while its Annotation says something else becomes `needs_decision`, with `human_note: "marked done outside kinetic"`.
- `write` sends `ops_for` for each changed published ticket in one `orbit batch`. A ticket id that is not yet a Task ID goes to the staged file (Task 4).

- [ ] **Step 1: Write the failing tests.** Make `OrbitContractTest` run the Task 1 contract against a temporary Board created with `orbit init`. Skip it with the message `orbit >= 0.11.0 not installed` when `orbit --version` is missing or older. Add these to `tests/test_orbit_store.py`:
  - `test_derive_matches_status_table`: one assertion per row of the spec's Status table, including `needs_decision` giving `in_progress` with the claim kept, `waiting_on` set and no hold label.
  - `test_ops_for_dispatch_unholds_and_claims_in_one_batch`: from `todo` to `running` gives `label remove [kinetic]` then `claim by kinetic-<run id>`, then `annotate`.
  - `test_no_op_mutation_sends_no_batch`: `ops_for(t, t) == []`, and `set_ticket` with unchanged fields makes no `orbit` call (patch `call`).
  - `test_blocked_by_becomes_dependency_and_annotation`: a `merge` edge gives `depend` plus `{"id", "type": "merge"}` in the Annotation.
  - `test_resume_clears_waiting_and_reclaims`: from `needs_decision` to `running` gives `update` with `clear_waiting: true` and `claim` by the same holder.
  - `test_done_releases_claim`: from `running` to `done` gives `done` by `kinetic-<run id>`.
  - `test_outside_done_on_agent_ticket_needs_decision` and `test_outside_done_on_human_ticket_is_human_done`.
  - `test_orbit_failure_leaves_state_json_untouched`: `call` raises, `set_ticket` raises `OrbitStoreError` whose message names the fix, and `state.json` bytes are unchanged.
  - `test_locked_is_retried`: `call` sees `LOCKED` twice, then `ok`, and the write succeeds.
  - `test_state_json_has_no_tickets`: after writes, `state.json`'s `tickets` is `{}`.

- [ ] **Step 2: Run and confirm failure**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_orbit_store tests.test_ticket_store -v`
Expected: FAIL with `ModuleNotFoundError: kinetic.orbit_store`.

- [ ] **Step 3: Implement** `orbit_store.py`. Orbit calls go through `call` only, so tests patch one function.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
Expected: PASS. `OrbitContractTest` passes where Orbit 0.11.0 or later is installed and is skipped with the message elsewhere.

- [ ] **Step 5: Commit**

```bash
git add scripts/kinetic/orbit_store.py scripts/kinetic/ticket_store.py tests/test_orbit_store.py tests/test_ticket_store.py
git commit -m "kinetic-orbit: Orbit ticket store reads and writes published tickets"
```

### Task 4: Stage and publish

**Files:**
- Modify: `scripts/kinetic/orbit_store.py` (`stage_path`, `publish`), `scripts/kinetic/state.py` (`record_gate` publishes on breakdown approval, new `publish_tickets(run_dir)` and CLI `publish-tickets`)
- Test: `tests/test_orbit_store.py`, `tests/test_state.py`

**Interfaces:**
- `OrbitTicketStore.stage_path(run_dir) = <run_dir>/tickets.staged.json`. `read` merges staged tickets over published ones, so `graph validate` and `graph topo` see both.
- `publish(run_dir, st) -> dict[str, str]`:
  - Sends one Batch. It adds every slice as a Parent Task with Type `epic`, and every staged ticket as a SubTask. Each one carries Source Key `kinetic:<run id>:<provisional id>`, the body read from `<run_dir>/issues/<provisional id>.md` with the board header lines removed (`board.parse_header` decides which), and the Labels and Annotation from `derive` and `ops_for`.
  - It then rewrites every reference (`blocked_by[].id`, `after`, `related`, `slice`, `st["slices"]`) to Task IDs from the returned key map, and deletes the staged file and the published issue files.
  - It returns the id map. The local store's `publish` returns the identity map and does nothing else.
- After publish, `write` also emits `done` on a slice's Parent Task in the same Batch that makes its last open SubTask Done.
- `state.publish_tickets(run_dir) -> dict[str, str]`, and `kinetic state publish-tickets --run <dir>` prints the map as JSON. `record_gate(run_dir, "breakdown", approved=True)` calls it after recording the gate.

- [ ] **Step 1: Write the failing tests:**
  - `test_staged_tickets_are_visible_to_graph_validate`: two staged tickets with a `merge` edge give `graph.validate` errors `[]` and `topo_order` in edge order.
  - `test_publish_creates_tasks_and_rewrites_ids` (Orbit contract, skipped without Orbit): after publish, `load()["tickets"]` keys are Task IDs, `blocked_by` points at Task IDs, `st["slices"]` holds Parent Task IDs, `orbit tree <slice>` lists the SubTasks, the staged file and issue files are gone, and the Orbit Board has one new commit.
  - `test_publish_twice_is_safe`: publish, put the staged file back as it was, publish again. Same Task IDs and Task count.
  - `test_slice_closes_when_last_ticket_done` (Orbit contract): the Batch that marks the last SubTask Done also marks the Parent Task Done.
  - `test_breakdown_approval_publishes` and `test_local_publish_is_identity` (local: `record_gate` breakdown leaves `state.json` tickets unchanged).

- [ ] **Step 2: Run and confirm failure**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_orbit_store tests.test_state -v`
Expected: FAIL (`AttributeError: publish_tickets`).

- [ ] **Step 3: Implement** staging and publish as specified above.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/kinetic/orbit_store.py scripts/kinetic/state.py tests/test_orbit_store.py tests/test_state.py
git commit -m "kinetic-orbit: stage tickets and publish them in one batch at the breakdown gate"
```

### Task 5: Liveness

**Files:**
- Modify: `hooks/_common.py` (new `touch_ticket(inp)`), `hooks/record_edit.py` and `hooks/claim_run.py` (call it last, inside `main`)
- Modify: `scripts/kinetic/orbit_store.py` (`touch`, and `read` sets `liveness`), `scripts/kinetic/status.py` (show stuck tickets)
- Test: `tests/test_hooks.py`, `tests/test_status.py`, `tests/test_orbit_store.py`

**Interfaces:**
- `_common.touch_ticket(inp) -> None`:
  - Finds the active run (`active_run(inp)`) and the ticket whose `worktree` contains `inp["cwd"]`.
  - Skips when `<run_dir>/touch/<ticket id>` has an mtime under 300 seconds old. Otherwise it updates that stamp and calls `ticket_store.for_state(st).touch(run_dir, st, ticket_id)`.
  - Swallows every exception after logging one line to stderr.
- `OrbitTicketStore.touch` runs `orbit heartbeat <id> --by kinetic-<run id>` (through `call`). `read` sets the derived key `liveness` on running tickets: `"stuck"` when `lease_until` is in the past, else `"alive"`. `write` ignores the `liveness` key. Tickets from the local store have no `liveness` key.
- `status.py` adds the line `implementer may be stuck: <id>` for each running ticket with `liveness == "stuck"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_hooks.py::test_touch_throttled`: two `record_edit` runs from inside a ticket worktree within 300 seconds call the fake store's `touch` once. With the stamp aged 301 seconds, it is called again.
  - `test_touch_failure_is_silent`: the fake store's `touch` raises, and the hook exits 0 with nothing on stdout.
  - `test_touch_outside_worktree_does_nothing`.
  - `test_status.py::test_stuck_ticket_is_reported`, and `test_local_status_unchanged` (output identical to today's for a local run).
  - `test_orbit_store.py::test_read_marks_stale_lease_stuck` (a fake `list` payload with a past `lease_until`).

- [ ] **Step 2: Run and confirm failure**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_hooks tests.test_status tests.test_orbit_store -v`
Expected: FAIL

- [ ] **Step 3: Implement** the hook helper, the store methods and the status line.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hooks/_common.py hooks/record_edit.py hooks/claim_run.py scripts/kinetic/orbit_store.py scripts/kinetic/status.py tests/test_hooks.py tests/test_status.py tests/test_orbit_store.py
git commit -m "kinetic-orbit: implementer liveness through ticket store touch"
```

### Task 6: Doctor, the vocabulary guard, and docs

**Files:**
- Modify: `scripts/kinetic/doctor.py` (`_tracker_checks` appends `ticket_store.store_for(ticket_store.for_tracker(kind)).health(settings)`)
- Modify: `scripts/kinetic/orbit_store.py` (`health`)
- Create: `tests/test_vocabulary.py`
- Modify: `GLOSSARY.md` (**Ticket store** entry, worded as in the spec, _Avoid_: adapter, backend, board), `README.md` (an "Orbit tracker" section: settings, what lives where, the hold Label line for `non_ready_labels`, liveness)
- Test: `tests/test_doctor.py`

**Interfaces:**
- `OrbitTicketStore.health(settings) -> list[dict]` rows, named exactly:
  - `orbit-binary` (pass, or fail "install orbit 0.11.0 or later")
  - `orbit-schema` (fail "orbit export schema_version is N, kinetic needs 3")
  - `orbit-board` (fail "set orbit_dir in settings.json or run orbit init in the repo")
  - `orbit-hold-label` (warn "add \"kinetic\" to non_ready_labels in the Board's config.toml")

- [ ] **Step 1: Write the failing tests:**
  - `test_doctor.py::test_orbit_tracker_adds_store_health` (patch `orbit_store.call` and the version probe) and `test_local_tracker_adds_no_store_rows`.
  - `test_vocabulary.py::test_orbit_named_only_where_allowed`: scan every file under `scripts/`, `hooks/`, `skills/`, `agents/` and `templates/`. Fail on any case-insensitive `orbit` outside the allowed list in Global Constraints. Print offending paths and line numbers.
  - `test_no_unqualified_adapter_for_ticket_store`: `ticket_store.py` and `orbit_store.py` docstrings and comments contain no `adapter` that isn't preceded by `tracker`.

- [ ] **Step 2: Run and confirm failure**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_doctor tests.test_vocabulary -v`
Expected: FAIL

- [ ] **Step 3: Implement** the health rows, the doctor hook-up and the docs.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 5: Smoke run against a real Orbit Board**, with Orbit 0.11.0 or later installed:
  - Create a `docs/smoke/orbit.md` checklist, in the style of the existing `docs/smoke/*.md`.
  - Run a quick-lane kinetic run on a scratch repo with `tracker: orbit`.
  - Check that `orbit tree` shows the slice, that `orbit list --label kinetic` empties as tickets dispatch, and that `kinetic status` shows no stuck tickets while the implementer works.

- [ ] **Step 6: Commit**

```bash
git add scripts/kinetic/doctor.py scripts/kinetic/orbit_store.py tests/test_doctor.py tests/test_vocabulary.py GLOSSARY.md README.md docs/smoke/orbit.md
git commit -m "kinetic-orbit: doctor health for the ticket store, vocabulary guard, docs"
```
