# Devin CLI smoke checklist

Manual acceptance test for `kinetic install --harness devin`. Run every step
on a real Devin CLI before Devin is announced as a supported harness; record
the date, `devin --version`, and pass/fail per step at the bottom.

Devin CLI support is **best effort**: plugin hooks are documented as
best-effort and fail open, so a guarantee only holds while the hooks actually
run. `kinetic doctor --harness devin` prints which guarantees are Enforced
and which are only Instructed.

## Setup

1. Install the Devin CLI and sign in: `devin auth login`.
2. From a kinetic git clone:

   ```
   <path-to-kinetic>/bin/kinetic install --harness devin
   ```

   - Expect `devin plugins install --local <clone>` to show a trust prompt
     listing kinetic's skills, hooks, rules and subagents — review and
     approve. (`-y` is deliberately not passed; the prompt is the consent.)
   - Re-running the command after `git pull` must succeed (a `--local` plugin
     is linked to the clone; the installer tolerates an already-installed
     plugin via `devin plugins list`).
3. `devin plugins list` shows `kinetic`; `devin plugins info kinetic` lists
   the skills and hooks.
4. `kinetic doctor --harness devin` — expect `hooks-registered: pass`,
   `hooks-trusted: warn` (best-effort note), `install-manifest: pass`.
5. In a Devin session inside any project:
   - `/hooks` lists kinetic's seven hooks sourced from
     `~/.config/devin/config.json` (PreToolUse/PostToolUse/Stop/SessionStart).
   - `/kinetic:status` (or any `/kinetic:<name>`) resolves — skills are
     namespaced `/<plugin>:<skill>`.
6. Check for double registration: Devin also loads the clone's
   `hooks/hooks.json` through Claude-plugin compatibility (with
   `--harness claude` and Claude tool matchers baked in). Its SessionStart
   and Stop hooks may fire a second time — a duplicated orientation line or
   verify-gate prompt is cosmetic, but record what `/hooks` shows and whether
   the Claude-format matchers ever fire on Devin tool names.

## 1. Quick-lane run end to end

- `/kinetic:run "<small self-contained idea>"` in a scratch repo registered
  with `/kinetic:init` (or an existing central config).
- Expect: lane picked with a one-line reason; Instructed guarantees stated
  at run start; grill questions in chat (Devin has no question tool); spec
  and breakdown gates answered in chat; implementers dispatched as
  `kinetic:<name>` subagents in the background; verify recorded; ship gate
  produces draft PRs (or stops at the gate if pushing is not wanted).
- Pass: the run reaches ship (or the ship gate) with no harness-specific
  errors; `kinetic status` reflects the run.

## 2. Isolation deny

- During a run, ask the orchestrator to have an implementer write outside the
  run workspace (e.g. "also update ~/other-repo/file.txt" or an absolute path
  outside the registered repos and run dir).
- Expect: the PreToolUse isolation hook blocks the edit with a reason naming
  the allowed roots. On Devin the deny surfaces as a blocked tool call
  (`decision: "block"`); there is no "ask" — the permission flow is the ask.
- Pass: the out-of-workspace write is denied, not merely discouraged.

## 3. Verify-gate block

- During a run, let an implementer edit a registered repo, then have it try
  to finish without a passing verify (or stop the session while edits are
  unverified).
- Expect: the Stop hook blocks with "Run verify: no passing verify after the
  last edit" plus the `kinetic verify` command to run.
- Pass: the agent cannot stop with stale verify; after running verify it can
  stop.

## 4. Gate question

- Reach any approval gate (spec, breakdown, ship, or a ticket decision).
- Expect: the question is asked in chat (Devin has no dedicated question
  tool); the run waits for the answer.
- Pass: the gate blocks progress until answered, then proceeds.

## 5. Decision resume / fresh fallback

- Get an implementer to `needs_decision` (e.g. ask it to choose between two
  approaches the brief leaves open, or answer a gate question with "decide
  for me").
- Answer the decision.
- Expect: because Devin cannot resume a subagent with its context
  (`resume_subagent: false` in the harness profile), kinetic starts a fresh
  implementer on the same worktree whose brief carries the previous report
  path, worktree and ruling id — the ticket still completes.
- Pass: the decision does not stall the run; the ticket reaches done with a
  passing verify.

## Facts this checklist must settle

- Whether `devin plugins install --local` is idempotent on re-run or needs
  the `plugins list` fallback the installer uses.
- Whether Devin loads the clone's `hooks/hooks.json` via Claude-plugin
  compat in addition to the generated `~/.config/devin/config.json` hooks
  (double SessionStart/Stop firing; whether `--harness claude` payloads
  confuse the run-scoped hooks — they should be inert outside a run).
- Whether subagent `tools:` frontmatter (Claude names: `Read, Edit, Write,
  Bash`) is honoured on Devin — `tools` is accepted as an alias for
  `allowed-tools`, but Devin tool names are lowercase (`exec`, `edit`,
  `write`). If names do not map, implementer subagents may lack `exec`.
- Whether the agent's `apply_patch` tool bypasses the isolation hook (its
  input carries a patch, not `file_path`; the devin normalizer does not parse
  patch headers yet — same gap as Codex US23).
- Whether Devin's session/hook cwd equals `DEVIN_PROJECT_DIR` closely enough
  for the run-scope cwd rule (the normalizer falls back to it when the
  payload has no `cwd`).
- Whether plugin hooks failing open ever drops a guarantee silently — watch
  for runs completing with unverified edits.

## Results

| Step | Result | Notes |
|------|--------|-------|
| Setup / install / doctor / /hooks / skill namespace | | |
| 1. Quick-lane run | | |
| 2. Isolation deny | | |
| 3. Verify-gate block | | |
| 4. Gate question | | |
| 5. Decision resume / fresh fallback | | |
| Open facts above | | |
