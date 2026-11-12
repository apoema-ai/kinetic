---
status: accepted
---

# Install kinetic with its own per-harness installer, not skills.sh alone

Kinetic is more than skills: it ships Python scripts, hooks, agent definitions and tracker adapters, and its guarantees depend on them. skills.sh copies or links only skill folders and has no post-install step, so it cannot install kinetic. We install from a git clone with `kinetic install --harness <h>`, using each harness's native mechanism where it carries everything and generated config where it does not:

- **Claude Code, Devin CLI**: register the clone as a local plugin (Devin reads `.claude-plugin` directly); skills are namespaced `/kinetic:<name>`.
- **Codex, OpenCode**: generate small `kntc-<name>` skill stubs (description starting "kinetic:", body "read and follow `<clone>/skills/<name>/SKILL.md`"), plus Codex `agents/openai.yaml` sidecars for user-invoked skills; generate agent definitions (Codex TOML, OpenCode markdown) from `agents/*.md`; merge hooks into the harness's hook config (Codex) or a local TS plugin that calls the Python hooks (OpenCode).
- **Everywhere**: a `kinetic` launcher on PATH replaces `${CLAUDE_PLUGIN_ROOT}` in skill text; hook commands use absolute paths into the clone and pass `--harness <h>`.

Updating is `git pull` plus re-running `kinetic install`; `doctor` flags stale generated files.

## Considered Options

- **skills.sh only**: leaves scripts, hooks and agents behind.
- **Native plugins only**: Codex plugin subagents and CLI plugin hooks are unconfirmed; OpenCode plugins are code, not bundles.
- **Symlink skill folders into `~/.agents/skills`**: kinetic's short names (`run`, `tdd`, `spec`) collide in that flat, shared folder.
- **Prefix `kinetic-` / `k-`**: `kinetic-` is long to type; `k-` is opaque and collision-prone. `kntc-` is short and distinctive.
