# Recovery

Use this when `~/.config/kinetic/active-run` points at an existing run directory (a new session, a crash, or `/kinetic:run` invoked again). Never re-initialise: `state init` refuses an existing state, and `--force` is only for an explicit user request to restart.

Never assume an agent from a previous session is alive. Re-derive everything from `state.json`, reports and git.

## On every entry

1. Load state: `python3 -m kinetic.state load --run <run_dir>` (phase, lane, tickets, repos, gates).
2. Stale tickets: `python3 -m kinetic.state stale-running --run <run_dir>` prints the ids marked `running` that have no report file. For each stale id:
   - Look at its worktree: `git -C <ticket worktree> log --oneline <integration-branch>..HEAD` and `git -C <ticket worktree> status --short`.
   - Tell the user what is there (commits, uncommitted files, nothing) and ask whether to re-dispatch an implementer or to set the ticket back to `todo`. Re-dispatch uses the normal brief from `build-loop.md`; keep the existing branch and worktree.
   - A `needs_decision` or `blocked` ticket whose agent is gone: its implementer cannot be resumed with SendMessage. Ask the user the same question again if it is unanswered (check `rulings`), then re-dispatch with the answer in the brief.
3. Tickets with a report file but still `running`: read the report's first lines and handle it as a return (`build-loop.md`, "On each implementer return").
4. `python3 -m kinetic.next_step --run <run_dir>` prints the suggested next command and why; use it to confirm where to continue.

## Continue

Resume at the recorded phase: re-read the guide for that phase and continue from the first unfinished step. Gates already recorded approved stay approved; a gate not recorded is asked again. If the phase is `build`, start a round with `kinetic.frontier`. If the user wants to abandon the run, `rm -f ~/.config/kinetic/active-run` only on their say-so.
