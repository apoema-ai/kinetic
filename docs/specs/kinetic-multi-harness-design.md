# Kinetic: support Codex CLI, OpenCode and Devin CLI as harnesses

Decided in a grilling session on 2026-11-11. Vocabulary: `GLOSSARY.md`. Install decision: `docs/adr/0001-own-installer-per-harness.md`.

## Problem Statement

Kinetic only runs inside Claude Code. Its packaging (`.claude-plugin`, `${CLAUDE_PLUGIN_ROOT}`), its hooks (Claude event names, tool names and output shapes), its build loop (Claude's background agent dispatch, SendMessage, AskUserQuestion, `model: "opus"`), its agent definitions (`model: sonnet|opus`, `tools:` allow-lists) and `doctor` (looks only under `~/.claude`) all assume it. A developer who works in Codex CLI, OpenCode or Devin CLI cannot use kinetic at all, and a team that mixes harnesses cannot share one pipeline.

## Solution

Kinetic runs as the orchestrator inside any of four **harnesses**: Claude Code, Codex CLI, OpenCode and Devin CLI. One source tree serves all four. `kinetic install --harness <h>` sets up each harness with the most enforcement it allows; every guarantee is either **Enforced** (a hook, plugin or script makes it hold) or **Instructed** (skill text only), and kinetic tells the user which. The floor on any harness is Instructed, the level of plain agent skills such as mattpocock/skills. Agents name a **model tier** (`standard`, `strong`) that each harness maps to a concrete model. A **harness profile** records what each harness can do, and every part of kinetic reads it instead of branching on the harness name.

Delivery order: Devin CLI, then Codex CLI, then OpenCode. Each ships when its `doctor` passes and its smoke checklist passes.

## User Stories

1. As a Devin CLI user, I want to install kinetic with one command, so that `/kinetic:run` works the same as in Claude Code.
2. As a Codex CLI user, I want to install kinetic with one command, so that I can drive a run from Codex.
3. As an OpenCode user, I want to install kinetic with one command, so that I can drive a run from OpenCode.
4. As a Claude Code user, I want my current setup to keep working unchanged, so that multi-harness support costs me nothing.
5. As a user on any harness, I want `doctor` to tell me which guarantees are Enforced and which are only Instructed on my harness, so that I am never misled about what kinetic protects.
6. As a user starting a run, I want the orchestrator to tell me the harness's Instructed guarantees, so that I know what to watch.
7. As a Codex user, I want `doctor` to fail until I have trusted kinetic's hooks, so that I do not run unprotected without knowing.
8. As a user, I want kinetic's skills on Codex and OpenCode to be named `kntc-<name>` with descriptions starting "kinetic:", so that they never collide with other skills named `run`, `tdd` or `spec`.
9. As a user, I want kinetic's user-only skills (`run`, `init`, `implement`, `status`, `ask`) to stay user-only on every harness, so that the model never starts a run on its own.
10. As a user, I want to update kinetic with `git pull` plus re-running `kinetic install`, so that updates are one step on every harness.
11. As a user, I want `doctor` to flag generated files that are stale against the clone, so that a forgotten re-install is caught.
12. As a user, I want to map the `standard` and `strong` tiers to models and reasoning effort for my harness, so that kinetic uses models my harness actually has.
13. As a user, I want sensible tier defaults per harness, so that I need no config to start.
14. As a user, I want fix round 3 to escalate to the `strong` tier on every harness, even where the harness cannot choose a model per dispatch.
15. As a user, I want an implementer that stopped on a decision to be resumed with my answer where the harness can resume it, so that it keeps its context.
16. As a user, I want a fresh implementer started from the saved report, worktree and ruling when resume is unavailable or fails, so that a decision never stalls the run.
17. As a user, I want crash recovery and "this harness cannot resume" to be the same path, so that both are equally tested.
18. As a user, I want reviewers to be unable to change the ticket worktree on every harness, so that a review never alters what it reviews.
19. As a user, I want a reviewer that changed the worktree to have its review discarded and re-run, so that a bad review never merges.
20. As a user, I want gates and decisions asked with my harness's question tool when it has one and in chat otherwise, so that gates work everywhere.
21. As a user, I want the isolation deny, the verify-before-stop gate and the write-op confirmation to be Enforced wherever my harness allows, so that the run is as safe as the harness permits.
22. As an OpenCode user, I want the verify gate enforced through the idle re-prompt and through `verify`/`ship` refusing to proceed on stale verify, so that OpenCode's missing Stop-block does not drop the gate.
23. As a Codex user, I want the isolation and edit-recording hooks to read file paths from `apply_patch` patches, so that Codex edits are checked like any other.
24. As a user, I want retro to propose edits to the instruction file my harness actually reads, so that its suggestions take effect.
25. As a user, I want the standards reviewer to keep reading every instruction file present, so that no standard is missed.
26. As a user, I want `doctor` to look for companion skills where my harness keeps skills, and to report plugin-only companions as "n/a, fallback used" on harnesses that cannot install them.
27. As a maintainer, I want one hook logic with per-harness input/output translation, so that a guarantee is written once.
28. As a maintainer, I want skill and agent text to describe actions instead of naming one harness's tools, so that the text works on all four.
29. As a maintainer, I want one place that knows each harness's capabilities, so that adding a harness means adding one profile.
30. As a maintainer, I want hook payload fixtures per harness in the test suite, so that translation regressions are caught in CI without the CLIs installed.

## Implementation Decisions

**Harness profile (new module `harness`, in this repo).** A static table keyed by harness id (`claude`, `devin`, `codex`, `opencode`). Fields: hook events available and whether Stop can block; hook trust step needed; tool names for shell, file edit/write, patch; whether a sub-agent can be resumed; whether model can be chosen per dispatch; question tool name or none; skill and agent directories; instruction files read, in order; whether plugin companions can be installed; tier defaults; which guarantees are Enforced. Interface: `profile(harness_id)`, and a CLI `kinetic harness [--harness h]` printing the active profile as short text for the orchestrator. The active harness comes from `--harness` (hook commands, installer) or from `~/.config/kinetic/settings.json` `harness` written by the installer. No environment sniffing.

**Installer (new module `install`).** `kinetic install --harness <h>` run from a git clone; idempotent; re-run after `git pull`. Per ADR 0001:
- Claude Code: registers the clone as a local plugin (as today).
- Devin CLI: `devin plugins install --local <clone>`; Devin reads `.claude-plugin` and namespaces `/kinetic:<name>`.
- Codex CLI: writes `kntc-<name>` stub skills into `~/.agents/skills` (name, description prefixed "kinetic:", body "Read and follow `<clone>/skills/<name>/SKILL.md`", plus `agents/openai.yaml` with `allow_implicit_invocation: false` for user-only skills); generates `~/.codex/agents/*.toml` from `agents/*.md` with the tier mapped to a model; merges kinetic's hook entries into `~/.codex/hooks.json` (only its own entries, marked so re-install replaces them); tells the user to trust them with `/hooks`.
- OpenCode: writes the same stubs into `~/.config/opencode/skills`; generates markdown agents into `~/.config/opencode/agents`; installs a small local TS plugin that forwards tool and session events to the Python hooks and maps their decisions back (throw to deny; re-prompt on idle for the verify gate; context injection for orientation).
- Everywhere: links `~/.local/bin/kinetic` to a launcher in the clone; records harness and clone path in `settings.json`; writes a manifest of generated files with a content hash so `doctor` can flag staleness. Never touches config entries it did not write.

**`kinetic` launcher.** Replaces `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.<module>` in every skill and agent with `kinetic <module> ...`. `kinetic root` prints the clone path, used where a skill reads another skill's file.

**Hooks.** The hook logic files stay as they are. `_common` gains a translation layer selected by `--harness`: it normalises input (session id, cwd — Devin uses `DEVIN_PROJECT_DIR` — tool name, file path, including paths parsed from `apply_patch` patch headers) into today's shape, and renders allow/deny/ask, block-stop and context-injection in the harness's output shape. Matchers in each harness's hook config use that harness's tool names from the profile. Fail-closed behaviour is unchanged.

**Model tiers.** Agent frontmatter names `tier: standard|strong` instead of `model:`. `implementer` and `fix-reviewer` are `standard`; `spec-reviewer`, `standards-reviewer`, `integration-reviewer` and a new `implementer-strong` (same body as `implementer`) are `strong`. `settings.json` may map each tier per harness to model and reasoning effort; profile defaults apply otherwise (Claude: sonnet/opus). Claude Code and Devin load `agents/*.md` straight from the clone, so each agent file keeps a `model:` line as the Claude/Devin default beside `tier:`, and the `settings.json` mapping does not affect those two harnesses; for Codex and OpenCode the generated definitions resolve the tier through the mapping. Skill-level `model:` lines stay as a Claude-only hint; no third tier.

**Build loop and gates.** Text describes actions: start the ready implementers in parallel in the background; ask the user (question tool if the profile names one, otherwise chat); use `implementer-strong` for fix round 3. The first step of `run` calls `kinetic harness` and states the Instructed guarantees. Decision resume: if the profile says the harness can resume, send the answer to the same implementer; if it cannot, or the resume fails, start a fresh implementer on the same worktree whose brief adds `Previous report: <path>` and `Ruling: <id>`. Both paths rely only on saved state; crash recovery uses the fresh path.

**Reviewer read-only check (new `gitops` subcommand `assert-unchanged`).** Before dispatching a reviewer the orchestrator records the ticket worktree's `HEAD` and porcelain status; after the reviewer returns, `kinetic gitops assert-unchanged --repo <wt> --head <sha> --status-hash <h>` exits non-zero on any change. On failure the orchestrator restores the worktree to the recorded state, discards the review and re-runs it once; a second failure goes to the user. Tool allow-lists stay where the harness supports them.

**User-only skills.** The five user-only SKILL.md files add `triggers: [user]` beside `disable-model-invocation: true`. Codex stubs carry `agents/openai.yaml`; OpenCode reads `disable-model-invocation`.

**Retro and standards.** Retro proposes edits to the first instruction file in the profile's list that exists in the repo (Claude: `CLAUDE.md`, `AGENTS.md`; Codex: `AGENTS.md`; OpenCode: `AGENTS.md`, then `CLAUDE.md`; Devin: `AGENTS.md`, `CLAUDE.md`). The standards reviewer reads all present.

**Doctor.** New checks: harness recorded; install manifest fresh; hooks registered (and trusted, on Codex); tier mapping resolvable; guarantee table (Enforced/Instructed) printed. Companion skills are searched in the profile's skill directories; plugin companions are checked only where the profile allows them, otherwise reported "n/a, fallback used".

## Testing Decisions

Tests check external behaviour at the highest existing seams, using the repo's `unittest` style with a temporary `HOME`.

- **Hook seam (existing, `test_hooks`).** Run each hook as a subprocess with a recorded stdin payload per harness and assert on stdout and state. Add per-harness payload fixtures (Claude, Devin, Codex incl. `apply_patch`, OpenCode as forwarded by its plugin) and assert each guarantee yields the harness's own output shape.
- **CLI seam for the installer.** Run `kinetic install --harness <h>` against a temp `HOME` and a fake clone; assert the generated files (stubs, `openai.yaml`, agent TOML/markdown, hooks entries, launcher, manifest), idempotency on re-run, and that foreign entries in an existing `hooks.json` are preserved. Harness CLIs that the installer shells out to (`devin plugins install`) are invoked through a fake on `PATH`.
- **`kinetic harness` and `doctor` (existing `test_doctor`).** Assert profile text per harness, the Enforced/Instructed table, stale-manifest detection, companion lookup per harness.
- **`gitops assert-unchanged` (existing `test_gitops`).** Real temp git repos: clean pass, new commit fails, dirty tree fails.
- **Skill text (existing `test_skill_text`).** No skill or agent names a Claude-only tool (AskUserQuestion, SendMessage, `run_in_background`, `${CLAUDE_PLUGIN_ROOT}`); agents declare `tier:`; user-only skills carry both invocation keys.
- **Manual smoke checklist per harness**, run before that harness ships: one quick-lane run end to end, one isolation deny, one verify-gate block, one gate question, one decision resume (or fresh fallback). Not automated: the CLIs need installs and sign-in.

## Threat model

- **Assets:** the user's repos and branches, harness config files (`~/.codex/hooks.json`, agent and skill dirs), tracker and GitHub write access, kinetic run state.
- **Actors and boundaries:** the user; the orchestrator agent; implementer and reviewer sub-agents (untrusted to follow text-only rules); the installer writing into harness config; content of repos and tickets (untrusted input to agents).
- **Abuse cases and mitigations:**
  - A sub-agent writes outside the run workspace → isolation hook (Enforced where the harness has a pre-tool hook, incl. Codex patch parsing); Instructed elsewhere and shown as such.
  - A reviewer edits the code it reviews → `assert-unchanged` after every review, Enforced on all harnesses.
  - The agent stops with unverified edits → Stop-block hook, or idle re-prompt plus `verify`/`ship` refusing stale verify on OpenCode.
  - The agent pushes, merges or writes to a tracker without confirmation → write-op confirmation hook where available; Instructed elsewhere and shown.
  - The installer clobbers a user's existing harness config → it edits only entries it marked as its own, and records every file it writes in the manifest.
  - Hook translation misreads a payload and allows a write → fail-closed: unparsable input on a pre-tool hook asks.
  - Stub skills point at a moved or deleted clone → `doctor` fails on a missing clone path.
  - A user believes a guarantee is enforced when it is not → `doctor` and the run start print the Instructed list.

## Non-functional requirements

- **Compatibility:** Claude Code behaviour unchanged for existing users; Python 3.9+, no new Python dependencies; the OpenCode plugin has no npm dependencies beyond OpenCode's plugin API.
- **Performance:** hook overhead stays within the current 10 s timeout and adds no network calls; translation is in-process.
- **Idempotency:** `kinetic install` re-runs safely and converges; generated files are fully regenerated, never patched.
- **Rollback:** `kinetic install --harness <h> --uninstall` removes every file and config entry listed in the manifest.
- **Observability:** `doctor` and `kinetic harness` show harness, clone path, tier mapping and the Enforced/Instructed table.
- **Privacy:** no telemetry; nothing leaves the machine except the existing tracker and git operations.

## Acceptance criteria

- [ ] `kinetic install --harness devin|codex|opencode|claude` sets up that harness from a git clone, is idempotent, and `--uninstall` removes everything it wrote.
- [ ] On Codex and OpenCode, kinetic's skills appear as `kntc-<name>`, descriptions start with "kinetic:", and user-only skills cannot be invoked by the model.
- [ ] No skill or agent file references `${CLAUDE_PLUGIN_ROOT}`, AskUserQuestion, SendMessage, `run_in_background`, and no skill or agent body names a concrete model; agents declare `tier:` (agent frontmatter keeps `model:` as the Claude/Devin default).
- [ ] Hooks produce correct decisions in each harness's output shape for recorded Claude, Devin, Codex (incl. `apply_patch`) and OpenCode payloads.
- [ ] `kinetic harness` prints the profile and the Instructed guarantees; `run` calls it first.
- [ ] Fix round 3 uses `implementer-strong` on every harness.
- [ ] A decision resumes the same implementer where the profile allows, and otherwise or on failure starts a fresh implementer from the saved report, worktree and ruling.
- [ ] `kinetic gitops assert-unchanged` detects a commit or dirty tree after a review; the orchestrator discards and re-runs that review once, then asks the user.
- [ ] On OpenCode, `verify`/`ship` refuse to proceed while verify is stale, and the idle re-prompt asks the agent to run verify.
- [ ] `doctor` reports harness, stale install, untrusted Codex hooks, tier mapping, Enforced/Instructed table, and companions per harness.
- [ ] Retro targets the first instruction file the harness reads.
- [ ] All existing tests pass; Claude Code behaviour is unchanged.
- [ ] The smoke checklist passes on Devin CLI, then Codex CLI, then OpenCode, each before that harness is documented as supported.

## Out of Scope

- Cloud Devin and any remote-VM harness.
- Using another harness as a worker under a Claude orchestrator (mixed-harness runs).
- Distribution through skills.sh or a public Codex/OpenCode marketplace.
- Other harnesses (Cursor, Copilot, Amp, Goose).
- Automated end-to-end tests that drive the real harness CLIs.

## Further Notes

Unconfirmed facts the smoke tests must settle: whether Codex loads hooks shipped in a plugin from the CLI (the design avoids relying on it); whether OpenCode's idle re-prompt is reliable enough to count as Enforced; whether symlinked or generated agent directories load on each harness; Devin's exact skill-level model key. If OpenCode's idle re-prompt proves unreliable, the verify gate on OpenCode is still Enforced at `verify`/`ship` and Instructed at stop.
