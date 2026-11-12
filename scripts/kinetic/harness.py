from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kinetic.config import ConfigError, _load

DEFAULT_SETTINGS = Path.home() / ".config/kinetic/settings.json"
DEFAULT_HARNESS = "claude"

HARNESS_IDS = ("claude", "devin", "codex", "opencode")

# The guarantees kinetic can keep; a profile's "enforced" list names the ones its
# hooks, plugin or scripts make hold. Anything else is Instructed (skill text only).
GUARANTEES = (
    "workspace-isolation",    # pre-tool deny of edits outside the run workspace
    "edit-recording",         # post-tool record of edits, input to the verify gate
    "verify-before-stop",     # stop gate: block, idle re-prompt, or verify/ship refusal
    "write-op-confirmation",  # confirm git push/merge/pr writes and tracker writes
    "deploy-confirmation",    # confirm deploy triggers
    "review-read-only",       # assert-unchanged discards a review that touched the worktree
)

# hooks.stop: "block" (Stop hook can stop the agent finishing), "reprompt"
# (idle re-prompt only, the agent can still stop) or "none".
_PROFILES = {
    "claude": {
        "id": "claude",
        "name": "Claude Code",
        "hooks": {
            "pre_tool_use": True,
            "post_tool_use": True,
            "session_start": True,
            "stop": "block",
            "trust": "none",
        },
        "tools": {
            "shell": "Bash",
            "edit": ["Write", "Edit", "MultiEdit", "NotebookEdit"],
            "patch": None,
        },
        "resume_subagent": True,       # SendMessage to a running agent
        "model_per_dispatch": True,    # Agent tool model: parameter
        "question_tool": "AskUserQuestion",
        "skill_dirs": ["~/.claude/skills"],
        "agent_dirs": ["~/.claude/agents"],
        "instruction_files": ["CLAUDE.md", "AGENTS.md"],
        "plugin_companions": True,
        "tier_defaults": {
            "standard": {"model": "sonnet"},
            "strong": {"model": "opus"},
        },
        "enforced": list(GUARANTEES),
    },
    "devin": {
        "id": "devin",
        "name": "Devin CLI",
        "hooks": {
            "pre_tool_use": True,
            "post_tool_use": True,
            "session_start": True,
            "stop": "block",
            "trust": "plugin install trust prompt",
        },
        # Plugin hooks are best effort and fail open on Devin; the guarantees
        # below hold whenever the hooks run (docs.devin.ai/cli/extensibility/plugins).
        "tools": {
            "shell": "exec",
            "edit": ["edit", "write"],
            "patch": None,
        },
        "resume_subagent": False,      # run_subagent/read_subagent, no resume
        "model_per_dispatch": False,   # run_subagent takes a profile, not a model
        "question_tool": None,
        "skill_dirs": ["~/.config/devin/skills", "~/.agents/skills"],
        "agent_dirs": ["~/.config/devin/agents"],
        "instruction_files": ["AGENTS.md", "CLAUDE.md"],
        "plugin_companions": True,     # devin plugins install; reads .claude-plugin
        "tier_defaults": {
            "standard": {"model": "sonnet"},
            "strong": {"model": "opus"},
        },
        "enforced": list(GUARANTEES),
    },
    "codex": {
        "id": "codex",
        "name": "Codex CLI",
        "hooks": {
            "pre_tool_use": True,
            "post_tool_use": True,
            "session_start": True,
            "stop": "block",  # Stop decision:"block" continues the turn
            "trust": "run /hooks and trust kinetic's hooks",
        },
        "tools": {
            "shell": "Bash",
            "edit": ["apply_patch"],
            "patch": "apply_patch",
        },
        "resume_subagent": True,       # resume_agent / followup_task
        "model_per_dispatch": True,    # spawn_agent model parameter
        "question_tool": None,
        "skill_dirs": ["~/.agents/skills"],
        "agent_dirs": ["~/.codex/agents"],
        "instruction_files": ["AGENTS.md"],
        "plugin_companions": False,
        "tier_defaults": {
            "standard": {"model": "gpt-5.1-codex", "effort": "medium"},
            "strong": {"model": "gpt-5.1-codex", "effort": "high"},
        },
        "enforced": list(GUARANTEES),
    },
    "opencode": {
        "id": "opencode",
        "name": "OpenCode",
        "hooks": {
            "pre_tool_use": True,    # plugin tool.execute.before, throw to deny
            "post_tool_use": True,   # plugin tool.execute.after
            "session_start": True,   # plugin context injection
            "stop": "reprompt",      # experimental.idle re-prompt; cannot block
            "trust": "none",
        },
        "tools": {
            "shell": "bash",
            "edit": ["edit", "write"],
            "patch": "patch",
        },
        "resume_subagent": True,      # task tool task_id resumes the child session
        "model_per_dispatch": True,   # task tool model param (v2 model_override permission)
        "question_tool": "question",
        "skill_dirs": ["~/.config/opencode/skills"],
        "agent_dirs": ["~/.config/opencode/agents"],
        "instruction_files": ["AGENTS.md", "CLAUDE.md"],
        "plugin_companions": False,
        "tier_defaults": {
            "standard": {"model": "anthropic/claude-sonnet-4-5"},
            "strong": {"model": "anthropic/claude-opus-4-1"},
        },
        # verify-before-stop stays Instructed: the idle re-prompt's reliability is
        # unconfirmed (spec Further Notes); verify/ship still refuses stale verify.
        "enforced": [g for g in GUARANTEES if g != "verify-before-stop"],
    },
}


class HarnessError(Exception):
    pass


def profile(harness_id: str) -> dict:
    """The harness profile record for harness_id (claude, devin, codex, opencode)."""
    try:
        return _PROFILES[harness_id]
    except KeyError:
        raise HarnessError(
            f"unknown harness '{harness_id}': expected one of {', '.join(HARNESS_IDS)}")


def active_harness(harness: str | None = None, settings: Path | None = None) -> str:
    """The active harness id: --harness wins, else settings.json "harness",
    else claude. Never sniffed from the environment."""
    if harness:
        profile(harness)  # validates
        return harness
    path = Path(settings) if settings else DEFAULT_SETTINGS
    try:
        cfg = _load(path)
    except ConfigError as e:
        raise HarnessError(str(e))
    hid = cfg.get("harness") or DEFAULT_HARNESS
    if not isinstance(hid, str):
        raise HarnessError(f"harness in {path} must be a string")
    return profile(hid)["id"]


def instructed(p: dict) -> list[str]:
    """Guarantees that are only Instructed (skill text) on this harness."""
    enforced = set(p["enforced"])
    return [g for g in GUARANTEES if g not in enforced]


def _yes(v) -> str:
    return "yes" if v else "no"


def _join_or_none(items) -> str:
    return ", ".join(items) if items else "none"


def _tier_text(tiers: dict) -> str:
    parts = []
    for name in ("standard", "strong"):
        fields = ",".join(f"{k}={v}" for k, v in sorted(tiers[name].items()))
        parts.append(f"{name}={fields}")
    return " ".join(parts)


def render(p: dict) -> str:
    h = p["hooks"]
    t = p["tools"]
    out = [
        f"Harness: {p['name']} ({p['id']})",
        f"Hooks: pre-tool={_yes(h['pre_tool_use'])} post-tool={_yes(h['post_tool_use'])} "
        f"session-start={_yes(h['session_start'])} stop={h['stop']} trust={h['trust']}",
        f"Tools: shell={t['shell']} edit={_join_or_none(t['edit'])} patch={t['patch'] or 'none'}",
        f"Resume sub-agent: {_yes(p['resume_subagent'])}",
        f"Model per dispatch: {_yes(p['model_per_dispatch'])}",
        f"Question tool: {p['question_tool'] or 'none'}",
        f"Skill dirs: {_join_or_none(p['skill_dirs'])}",
        f"Agent dirs: {_join_or_none(p['agent_dirs'])}",
        f"Instruction files: {_join_or_none(p['instruction_files'])}",
        f"Plugin companions: {_yes(p['plugin_companions'])}",
        f"Tiers: {_tier_text(p['tier_defaults'])}",
        f"Enforced: {_join_or_none(p['enforced'])}",
        f"Instructed: {_join_or_none(instructed(p))}",
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kinetic.harness")
    ap.add_argument("--harness", choices=HARNESS_IDS, default=None,
                    help="harness id; default: settings.json 'harness' or claude")
    a = ap.parse_args(argv)
    try:
        hid = active_harness(a.harness)
    except HarnessError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(render(profile(hid)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
