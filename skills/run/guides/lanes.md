# Lanes and entry points

## Pick the lane

First collect the candidate repos you already know: repos named in the ref text, the repo the tracker issue names, and the registered repo `/kinetic:run` was started from (its path in `~/.config/kinetic/repos.json` contains the current directory). Do not ask the user for repos here; the discover phase settles them.

- **Repo known at intake:** pick the lane as below. Only here can the lane be `quick`.
- **Repo not known:** record `feature` as a provisional lane and start at the grill. The discover phase sets the final lane with `kinetic state set-lane`: one repo is `feature`, two or more is `epic`. `set-lane` only moves between `feature` and `epic`.

Size and uncertainty are judgment calls; state your pick and why in one line and let the user override.

| Lane | When | Phases |
|---|---|---|
| quick | One small ticket, one repo known at intake, no design decisions | intake, discover, build, review, ship, retro |
| feature | One repo, needs a spec | grill, discover, specify, decompose, build, review, ship, retro |
| epic | Several repos | all phases; per-repo integration branches, typed edges |

Quick lane: no grill, spec or decompose phase. Order: intake, discover (`Mode: confirm-only` on the one repo), the breakdown gate, build. Its gates are a one-question breakdown gate (it records the grant, see `gates.md`) and the ship gate. You create the one ticket yourself in state:

```
kinetic state set-ticket --run <run_dir> --id <id> --field repo=<repo> --field 'blocked_by=[]'
```

The id is the tracker reference if the ref is one, else `01-<repo>-<slug>` (local mode). Then ask the breakdown gate with just that one ticket (id, repo, no blockers) and the seams to test (the implementer has no one to ask, see `agents/implementer.md`), record it, and go to build. `build-loop.md` writes `<run_dir>/issues/<id>.md` from the ref before dispatch.

## Entry point: start at the first missing artifact

| What the user has | Start at |
|---|---|
| Idea or bare ticket | grill |
| Spec, no tickets | discover, then spec gate and tickets |
| Spec and tickets with edges | discover (`Mode: confirm-only` on the tickets' repos), then build |
| One small ticket, no spec | quick lane |

How to check each artifact: a spec exists as a tracker issue the ref points to (fetch it through the adapter named by `kinetic tracker resolve`) or `<run_dir>/spec.md`; run `kinetic spec_lint <spec-file>` on a local one and treat lint errors as "spec missing" until fixed. Tickets exist when `kinetic state load --run <run_dir>` shows non-empty `tickets` or the tracker has child tickets for the spec (then register them with `set-slices` and `set-ticket` as in `skills/decompose/SKILL.md` step 5).

A spec brought in from outside still needs the spec gate before tickets. Tickets brought in still need the breakdown gate before build, because the gate records the grant.

## `--from build`

Skips straight to build, after discover in `Mode: confirm-only` on the ticket repos. Requires tickets already in state, or a ticket ref (the `/kinetic:implement` case): for a ref, register that one ticket as in the quick lane, including the seams question; `build-loop.md` writes `<run_dir>/issues/<id>.md` from the ref (a ticket file outside the run dir is copied there). If neither exists, say so and point at `/kinetic:run <ref>` without the flag. The breakdown gate still applies: record it before dispatching.
