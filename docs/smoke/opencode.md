# OpenCode smoke checklist

Manual acceptance test for `kinetic install --harness opencode`. Run every
step on a real OpenCode before OpenCode is announced as a supported harness;
record the date, `opencode --version`, and pass/fail per step at the bottom.

This checklist is a **user gate**: the implementer cannot run it — the plugin
only takes effect inside a live OpenCode session, and the run itself needs a
human at the gates.

OpenCode hooks are **Enforced through the plugin**: `tool.execute.before`
denies by throwing, `permission.evaluate` turns kinetic "ask" decisions into
OpenCode permission prompts, `execute.after` records edits, and
`experimental.idle` re-prompts the agent to run verify. There is no trust
step and no Stop-block: the idle re-prompt is bounded (the plugin stops after
three ignored rounds per session) and the API is marked experimental, so
`verify-before-stop` stays **Instructed** on OpenCode — while
`verify`/`ship` refusing stale verify is **Enforced** at the CLI layer on
every harness (`kinetic state set-phase --phase ship` and
`record-gate ship --approved true` refuse while any repo's verify is stale).

## Setup

1. Install OpenCode (`opencode` on PATH or the desktop app; tested against
   `opencode v2.x`).
2. From a kinetic git clone:

   ```
   <path-to-kinetic>/bin/kinetic install --harness opencode
   ```

   - Expect: `kntc-<name>.md` stub skills under `~/.config/opencode/skills`,
     agent markdown under `~/.config/opencode/agents`, and the plugin at
     `~/.config/opencode/plugins/kinetic.ts`. No `opencode.json` edit and no
     trust step — OpenCode file-drops `plugins/*.ts`.
   - Re-running after `git pull` must be idempotent; foreign plugins in the
     same directory (e.g. `rtk.ts`) are preserved.
   - `--uninstall` removes exactly the manifest-listed files and prunes the
     skills/agents dirs only when empty.
3. `kinetic doctor --harness opencode` — expect `hooks-registered: pass`
   (plugin present and pointing at the clone), `hooks-trusted: na`,
   `install-manifest: pass`, `tier-mapping: pass`.
4. In an OpenCode session:
   - Skills resolve as `kntc-<name>`; the five user-only skills plus
     `kntc-doctor` carry `disable-model-invocation: true` and must not
     auto-trigger.
   - `~/.config/opencode/agents/*.md` exist for the six kinetic agents with
     `mode: subagent`, `model` resolved from the tier (`standard` →
     `anthropic/claude-sonnet-4-5`, `strong` → `anthropic/claude-opus-4-1`,
     overridable via `tiers.opencode` in `~/.config/kinetic/settings.json`),
     and `permissions` deny rules for the tool groups each agent's
     `tools:` allow-list omits (reviewers get `edit: deny`).

## 1. Install / idempotency / uninstall

- Re-run `kinetic install --harness opencode`: identical manifest, no
  duplicated files, foreign plugins untouched.
- `kinetic install --harness opencode --uninstall`: removes the launcher
  link (unless another harness's manifest claims it), settings keys it
  wrote, all `kntc-*` stubs, agent files and `kinetic.ts`; foreign plugins
  and foreign files survive; empty generated dirs are pruned.
- Pass: install → doctor clean → uninstall leaves no kinetic traces and no
  collateral damage.

## 2. Quick-lane run end to end

- `kntc-run "<small self-contained idea>"` in a scratch repo registered with
  `kntc-init` (or an existing central config).
- Expect: lane picked with a one-line reason; Instructed guarantees stated
  at run start; orientation context injected into the session (the plugin's
  `session context` hook pushes `kinetic run … / phase … / next …` into the
  system prompt once a minute); grill questions via the `question` tool;
  spec and breakdown gates; implementers dispatched through the `task` tool
  with per-dispatch model; verify recorded; ship gate produces draft PRs.
- Pass: the run reaches ship (or the ship gate) with no harness-specific
  errors; `kinetic status` reflects the run.

## 3. Isolation deny

- During a run, have an implementer write outside the run workspace via
  `edit`/`write` (`path` outside the registered repos and run dir), via
  `patch` (a `*** Update File:` header outside), and via `shell`
  (`echo x > /tmp/outside` is allowed — shell writes are not path-checked;
  the isolation hook covers the file tools, same as Claude).
- Expect: `tool.execute.before` throws; OpenCode surfaces the error to the
  model as a tool failure naming the allowed roots.
- Pass: the out-of-workspace edit/patch is denied, not merely discouraged —
  for **every** file in a multi-file patch.

## 4. Edit recording

- After an implementer edits a file in a registered repo, check
  `kinetic state load --run <dir>`: the repo's `last_edit_at` is stamped.
- Pass: edits via `edit`, `write` and `patch` all stamp; a failed tool call
  (`status: error`) stamps nothing.

## 5. Stale verify refusal (Enforced)

- With a run active and a repo edited after its last verify, run
  `kinetic state set-phase --run <dir> --phase ship` and
  `kinetic state record-gate --run <dir> --gate ship --approved true`.
- Expect: both refuse non-zero with "verify is stale" and the per-repo
  `kinetic verify` command. After `kinetic verify` passes for that repo,
  both succeed.
- Pass: ship cannot proceed on stale verify even if the agent ignores the
  idle re-prompt.

## 6. Idle re-prompt (verify gate, Instructed/best-effort)

- Let an implementer edit a registered repo, then have it try to finish
  without running verify and go idle.
- Expect: `experimental.idle` fires `completion_gate.py`; on "block" the
  plugin calls `ctx.session.synthetic` and the agent gets another round
  with the "Run verify" reason (up to three times per session).
- Pass: the agent is asked to run verify before it can idle; record whether
  the re-prompt actually continues the session on your OpenCode version —
  this is the fact the checklist exists to settle.

## 7. Write/deploy confirmation

- Have the agent run `git push` (or an MCP write like
  `github_create_pull_request` / `atlassian_create_issue`) during a run.
- Expect: `confirm_write_ops` asks → `permission.evaluate` sets
  `effect: "ask"` with kinetic's reason → OpenCode's permission prompt
  appears. A push to a protected branch (`main`, `master`, `Release*`) is a
  hard deny (thrown error). Deploy-pattern MCP tools (`*deploy*`,
  `tekton*trigger*`) ask via `confirm_deploy`.
- Pass: the user is prompted with kinetic's reason, and deny is final.

## 8. Context / orientation injection

- Start a session while a run is active (active-run pointer set).
- Expect: within the first model call the system prompt gains the
  orientation lines (`kinetic run …`, `lane`, `phase`, `next`, `why`),
  refreshed about once a minute.
- Pass: the agent sees run orientation without any skill invocation.

## Facts this checklist must settle

- Whether `experimental.idle` + `ctx.session.synthetic` reliably continues
  the session on your OpenCode version (the API is marked experimental; if
  it proves unreliable the verify gate stays Instructed at stop — the
  `verify`/`ship` CLI refusal is unaffected).
- Whether `permission.evaluate` fires for tool calls whose configured
  effect would already be `allow` (needed for the ask escalation); if it
  does not, "ask" degrades to allow on permissive configs — record it.
- Whether MCP tool effective names match the plugin's write-op/deploy
  patterns (`<server>_<tool>` containing `atlassian`/`github`/`deploy`/
  `tekton…trigger`); if OpenCode namespaces them differently those two
  guarantees degrade to Instructed until the patterns are updated.
- Whether `ctx.session.get` returns `location.directory` for every session
  (it supplies the hooks' `cwd`); sessions where it fails fall back to the
  plugin process's cwd.
- Whether `patch` is the only multi-file edit path (edit/write are single
  `path`), and whether `*** Move to:` destinations outside the workspace
  are denied like Codex's.
- Whether the `task` subagent tool honours the agent files' `model` and
  `permissions`, and whether `mode: subagent` agents appear in the task
  catalog.
- Whether the v1 `server()` fallback behaves on OpenCode 1.x (deny +
  recording only; ask/orient/idle have no v1 channel).
- Whether `python3` resolves on OpenCode's PATH inside the plugin host —
  the plugin spawns `python3` by name; a missing interpreter fails open
  (logged to the plugin host's console).

## Results

| Step | Result | Notes |
|------|--------|-------|
| Setup / install / idempotency / uninstall / doctor | | |
| 2. Quick-lane run | | |
| 3. Isolation deny | | |
| 4. Edit recording | | |
| 5. Stale verify refusal | | |
| 6. Idle re-prompt | | |
| 7. Write/deploy confirmation | | |
| 8. Context injection | | |
| Open facts above | | |
