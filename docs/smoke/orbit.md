# Orbit tracker smoke checklist

Manual acceptance test for `tracker: orbit`. Run it once against a real Orbit
Board with an `orbit` build that has Batches and Annotations, and record the
date, `orbit --version`, and pass/fail per step at the bottom.

## Setup

1. A scratch repo with a verify command, registered with `/kinetic:init`.
2. `orbit init` in that repo; add `"kinetic"` to `non_ready_labels` in the
   Board's `config.toml`.
3. `~/.config/kinetic/settings.json`: `{"tracker": "orbit"}` (add
   `tracker_settings.orbit_dir` if the Board is not in the repo).
4. `kinetic doctor`: `orbit-binary`, `orbit-board`, `orbit-schema` and
   `orbit-hold-label` all pass.

## Run

5. Start a feature-lane run with two tickets, one blocked by the other.
6. Before the breakdown gate: `orbit list --label kinetic-run-<run id>` is
   empty and `<run_dir>/tickets.staged.json` holds both tickets.
7. Approve the breakdown gate: `orbit tree <slice id>` shows the Parent Task
   and both SubTasks; the second depends on the first; both carry `kinetic`.
8. When the first ticket dispatches: `orbit show <id>` is `in_progress`,
   claimed by `kinetic-<run id>`, without the `kinetic` label;
   `orbit ready` (from another shell) never offers it.
9. While the implementer works, `/kinetic:status` shows no stuck ticket and
   `lease_until` moves forward at least every 5 minutes.
10. After both tickets are done, the slice's Parent Task is `done`.
11. Mark a human ticket done with `orbit done <id>`; `/kinetic:status` shows
    it done.

## Results

| Date | `orbit --version` | Steps passed | Notes |
|---|---|---|---|
