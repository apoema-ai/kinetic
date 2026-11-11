# kinetic

kinetic is a Claude Code plugin that drives an SDLC pipeline: grill an idea, write a spec, split it into tickets with typed dependency edges, build across one or more repos with isolated implementers, review, ship, and run a retro. Scripts (Python stdlib, no LLM calls) own all state and graph logic; skills and agents do the judgment work; hooks enforce the rules.

## Install

For local use, point Claude Code at a checkout:

```
claude --plugin-dir <path-to-kinetic>
```

Requires macOS or Linux, Python 3.9+, git. Then run `/kinetic:init` first: it registers your repos, detects verify commands, picks the tracker (Jira or local) and writes `~/.config/kinetic/`. `/kinetic:doctor` checks the result.

## Lanes

- **`epic`**: several repos. All phases, per-repo integration branches, typed edges. Starts at grill for an idea or bare ticket, or at tickets (repo detection first) when you already have a spec.
- **`feature`**: one repo, needs a spec. grill, spec, tickets, build, review, ship, retro.
- **`quick`**: one small ticket, no spec. Intake, build, review, ship, retro; one breakdown question records the grant.

`/kinetic:run` picks the lane from what you hand it. Phases and approval gates are set only by `/kinetic:run`.

## Commands

| Command | What it does |
|---|---|
| `/kinetic:run <JIRA-KEY\|idea\|spec-path> [--from build]` | Orchestrates a run end to end, stopping at each gate |
| `/kinetic:implement <ref>` | Alias for `run --from build` on an already specified ticket |
| `/kinetic:init` | One-time setup of repos, verify commands, tracker |
| `/kinetic:doctor` | Read-only health check with a one-line fix per failure |
| `/kinetic:status` | Phase, tickets, frontier and gates of the active run |
| `/kinetic:ask` | Prints the lanes and the next step computed by `next_step` |

Dependency edges are exactly `snapshot`, `merge` and `release` (Jira labels `edge:snapshot`, `edge:merge`, `edge:release`). At most 3 implementers run at once and at most 1 per repo.

## Where state lives

- Run dir (default under `~/workspace/kinetic-runs`): `state.json` (flock-guarded), `logs/`, `reports/`, `reviews/`, and `worktrees/<repo>-<ticket>`.
- `~/.config/kinetic/repos.json`: per-repo `verify` (required), `publish_snapshot`, `pin`, `base_branch` (default `main`). A repo-root `.kinetic.json` wins key by key.
- `~/.config/kinetic/settings.json`: tracker, Jira project and issue types, `workspace_root`.
- `~/.config/kinetic/active-run`: absolute path of the active run dir; absent means no run.

## What the hooks enforce

- **Stop**: blocks "done" while a repo has edits newer than its last passing verify.
- **Isolation (PreToolUse)**: file writes outside registered repos and the run dir are denied.
- **Write-ops**: `git push` to `main`, `master` or `Release*` is denied; other pushes, `gh pr` writes, and Jira or GitHub write calls ask first.
- **Deploy**: deploy and tekton-trigger MCP calls ask first.
- **PostToolUse**: records edits so the Stop gate can compare them with verifies.
- **SessionStart**: orients the session to the active run.

## Known limitations

- The active-run pointer is machine-global, so the hooks act on every Claude session while a run is active.
- A bare `git push` on a protected branch only asks; it is not denied.
- `gh api` calls (including merges) pass through the write-ops hook, and base branches other than `main`, `master` and `Release*` are not protected.
- Isolation cannot tell implementers apart within the run dir.

## Tests

```
PYTHONPATH=scripts python3 -m unittest discover -s tests -v
```

## License

Some skills are adapted from third-party work; see `THIRD_PARTY_LICENSES.md`.
