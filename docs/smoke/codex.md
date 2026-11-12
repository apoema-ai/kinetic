# Codex CLI smoke checklist

Manual acceptance test for `kinetic install --harness codex`. Run every step
on a real Codex CLI before Codex is announced as a supported harness; record
the date, `codex --version`, and pass/fail per step at the bottom.

This checklist is a **user gate**: the implementer cannot run it — Codex
hooks only take effect after interactive trust, and the run itself needs a
human at the gates.

Codex hooks are **Enforced while trusted**: once `/hooks` trusts them they
block tool calls and stops like Claude's; before trust they do not run at
all. `kinetic doctor --harness codex` reports `hooks-registered` (entries in
`~/.codex/hooks.json`) separately from `hooks-trusted` (the `trusted_hash`
state Codex writes to `~/.codex/config.toml` `[hooks.state]`), and fails
until every kinetic hook is trusted.

## Setup

1. Install Codex CLI (`codex` on PATH; `codex-cli >= 0.16x` with hooks
   support — `[features] hooks` is stable and on by default).
2. From a kinetic git clone:

   ```
   <path-to-kinetic>/bin/kinetic install --harness codex
   ```

   - Expect: `kntc-<name>` stub skills under `~/.agents/skills`, agent TOML
     under `~/.codex/agents`, merged hooks in `~/.codex/hooks.json`, and a
     note to run `/hooks`.
   - Re-running after `git pull` must be idempotent: foreign hook entries in
     `hooks.json` are preserved, kinetic's `--harness codex` entries are
     replaced in place.
3. Open Codex and run `/hooks`. Expect kinetic's seven hooks listed
   (PreToolUse/PostToolUse on edits and `Bash`, Stop, SessionStart); review
   and **trust** them. Until trusted, Codex skips them — doctor reports
   `hooks-trusted: fail`.
4. `kinetic doctor --harness codex` — expect `hooks-registered: pass`,
   `hooks-trusted: pass` after `/hooks`, `install-manifest: pass`,
   `tier-mapping: pass`.
5. In a Codex session:
   - Skills resolve as `kntc-<name>` (explicit invocation `$kntc-run`);
     the five user-only skills (`kntc-run`, `kntc-init`, `kntc-implement`,
     `kntc-status`, `kntc-ask`, plus `kntc-doctor`) carry
     `policy.allow_implicit_invocation: false` in their `agents/openai.yaml`
     and must not auto-trigger.
   - `~/.codex/agents/*.toml` exist for the six kinetic agents with
     `model`/`model_reasoning_effort` resolved from the tier defaults
     (`standard` → `gpt-6.1-sol`/`medium`, `strong` → `gpt-6-astra`/`high`,
     overridable via `tiers.codex` in `~/.config/kinetic/settings.json`).

## 1. Quick-lane run end to end

- `$kntc-run "<small self-contained idea>"` in a scratch repo registered
  with `$kntc-init` (or an existing central config).
- Expect: lane picked with a one-line reason; Instructed guarantees stated
  at run start; grill questions in chat (Codex has no kinetic question
  tool); spec and breakdown gates answered in chat; implementers dispatched
  as `kntc-*` agent types via `spawn_agent` with per-dispatch model;
  verify recorded; ship gate produces draft PRs (or stops at the gate).
- Pass: the run reaches ship (or the ship gate) with no harness-specific
  errors; `kinetic status` reflects the run.

## 2. Isolation deny

- During a run, have an implementer write outside the run workspace — both
  via `apply_patch` (`*** Update File: /etc/...` or any path outside the
  registered repos and run dir) and via `Bash` (`echo x > /tmp/outside`).
- Expect: the PreToolUse isolation hook blocks with a reason naming the
  allowed roots. Codex denies via `hookSpecificOutput.permissionDecision:
  deny` (equivalently `decision: "block"` + `reason`).
- Pass: the out-of-workspace write is denied, not merely discouraged — for
  **every** file in a multi-file patch (one bad path denies the whole
  patch).

## 3. Verify-gate block

- During a run, let an implementer edit a registered repo, then have it try
  to finish without a passing verify (or stop the session while edits are
  unverified).
- Expect: the Stop hook blocks with `decision: "block"` and a reason
  containing "Run verify" plus the `kinetic verify` command.
- Pass: the agent cannot stop with stale verify; after running verify it
  can stop.

## 4. Gate question

- Reach any approval gate (spec, breakdown, ship, or a ticket decision).
- Expect: the question is asked in chat (Codex has no dedicated question
  tool wired into kinetic); the run waits for the answer.
- Pass: the gate blocks progress until answered, then proceeds.

## 5. Decision resume / fresh fallback

- Get an implementer to `needs_decision`, then answer the decision.
- Expect: Codex supports sub-agent resume (`resume_agent`/`followup_task`;
  `resume_subagent: true` in the harness profile), so kinetic resumes the
  same agent with its context. If resume proves unreliable in practice,
  record it — the fresh-implementer fallback must still complete the
  ticket.
- Pass: the decision does not stall the run; the ticket reaches done with
  a passing verify.

## Facts this checklist must settle

- Whether Codex's `apply_patch` is the only file-edit path (no separate
  write/edit tool bypassing the `apply_patch|Write|Edit` matcher), and
  whether `*** Move to:` destinations outside the workspace are denied.
- Whether MCP tool names on Codex match the `mcp__.*atlassian.*` /
  `mcp__.*github.*` / `mcp__.*deploy.*` matchers used by the write-op and
  deploy confirmation hooks; if Codex names them differently those two
  guarantees degrade to Instructed until matchers are updated.
- Whether `spawn_agent` honours the TOML `model`/`model_reasoning_effort`
  and `[[skills.config]]` entries, and whether `agent_type` resolves the
  generated `~/.codex/agents/*.toml` names.
- Whether untrusted or disabled hooks are silently skipped (they are — that
  is why `hooks-trusted` fails in doctor) and whether `/hooks` re-review is
  needed after `kinetic install` rewrites entries (hash changes => Modified
  => re-trust).
- Whether hook commands run through a shell (the generated commands rely on
  `python3 "<path>" --harness codex` quoting).
- Whether Codex's `cwd` in hook payloads matches the run-scope rule often
  enough (the normalizer trusts the payload `cwd`; there is no
  DEVIN_PROJECT_DIR-style fallback).

## Results

| Step | Result | Notes |
|------|--------|-------|
| Setup / install / doctor / /hooks trust / skill namespace | | |
| 1. Quick-lane run | | |
| 2. Isolation deny | | |
| 3. Verify-gate block | | |
| 4. Gate question | | |
| 5. Decision resume / fresh fallback | | |
| Open facts above | | |
