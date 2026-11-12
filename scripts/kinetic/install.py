from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from kinetic import harness
from kinetic.config import ConfigError, _load
from kinetic.state import atomic_write

MANIFEST_VERSION = 1

# settings.json keys the installer owns. Values recorded per install so
# --uninstall can restore what was there before (None = key was absent).
SETTING_KEYS = ("harness", "clone")


def _clone_root() -> Path:
    # scripts/kinetic/install.py -> parents[2] is the clone root.
    return Path(__file__).resolve().parents[2]


def _config_dir(home: Path) -> Path:
    return home / ".config" / "kinetic"


def _settings_path(home: Path) -> Path:
    return _config_dir(home) / "settings.json"


def _manifest_path(home: Path, harness_id: str) -> Path:
    return _config_dir(home) / f"install-manifest-{harness_id}.json"


def _bin_dir(home: Path) -> Path:
    return home / ".local" / "bin"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_link(path: Path) -> str:
    return _sha256_bytes(os.readlink(path).encode())


def _hash_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_manifest(path: Path):
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _git_toplevel(path: Path):
    try:
        p = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return Path(p.stdout.strip())


def _check_clone(clone: Path) -> str | None:
    """None when clone is a git worktree root, else an error message."""
    top = _git_toplevel(clone)
    if top is None or os.path.realpath(top) != os.path.realpath(clone):
        return (f"kinetic install must run from a git clone: {clone} is not "
                f"the root of a git worktree")
    if not (clone / "bin" / "kinetic").is_file():
        return f"kinetic install: clone is missing its launcher {clone / 'bin' / 'kinetic'}"
    return None


def _link_entry(link: Path, target: Path):
    return {"type": "symlink", "target": str(target),
            "sha256": _sha256_bytes(str(target).encode())}


def _write_generated_files(generated: dict) -> None:
    """Write every {path: text} generated file, creating parent dirs."""
    for path, text in generated.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, text)


def _generated_files(link: Path, launcher: Path, generated: dict) -> dict:
    """Manifest 'files' entries: the launcher symlink plus every generated
    file hashed by content (call after _write_generated_files)."""
    files = {str(link): _link_entry(link, launcher)}
    for path in generated:
        files[str(path)] = {"type": "file", "sha256": _hash_file(path)}
    return files


def _ensure_link(link: Path, launcher: Path, prev_files: dict) -> int:
    """Point link at launcher, replacing only files a previous install wrote.
    A link already aimed at this launcher is accepted even when another
    harness's manifest recorded it. Returns 0, or 1 after printing why a
    foreign file blocked the install."""
    if os.path.lexists(link):
        if link.is_symlink() and os.readlink(link) == str(launcher):
            pass  # already ours and correct
        elif str(link) in prev_files and (link.is_symlink() or link.is_file()):
            link.unlink()  # a file a previous kinetic install wrote
        else:
            print(f"kinetic install: refusing to overwrite existing {link} "
                  f"(not written by kinetic); remove it and re-run",
                  file=sys.stderr)
            return 1
    if not (link.is_symlink() and os.readlink(link) == str(launcher)):
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(launcher)
    return 0


def _write_install_settings(home: Path, clone: Path, hid: str, prev) -> tuple | None:
    """Record harness+clone in ~/.config/kinetic/settings.json.
    Returns (settings_path, existed, previous) or None after printing the
    ConfigError. A re-install keeps the FIRST install's rollback point."""
    settings_path = _settings_path(home)
    existed = settings_path.is_file()
    try:
        cfg = _load(settings_path)
    except ConfigError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return None
    prev_sent = prev.get("settings") or {}
    if prev_sent.get("writes"):
        previous = prev_sent.get("previous") or {
            k: None for k in SETTING_KEYS}
        existed = bool(prev_sent.get("existed", existed))
    else:
        previous = {k: (cfg[k] if k in cfg else None) for k in SETTING_KEYS}
    cfg["harness"] = hid
    cfg["clone"] = str(clone)
    atomic_write(settings_path,
                 json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    return settings_path, existed, previous


def _settings_manifest(settings_path: Path, hid: str, clone: Path,
                       existed: bool, previous: dict) -> dict:
    return {
        "path": str(settings_path),
        "existed": existed,
        "writes": {"harness": hid, "clone": str(clone)},
        "previous": previous,
    }


def _install_claude(clone: Path, home: Path) -> int:
    launcher = clone / "bin" / "kinetic"
    link = _bin_dir(home) / "kinetic"
    manifest_path = _manifest_path(home, "claude")
    prev = _read_manifest(manifest_path) or {}
    prev_files = prev.get("files") or {}

    if _ensure_link(link, launcher, prev_files) != 0:
        return 1
    res = _write_install_settings(home, clone, "claude", prev)
    if res is None:
        return 1
    settings_path, existed, previous = res

    manifest = {
        "version": MANIFEST_VERSION,
        "harness": "claude",
        "clone": str(clone),
        "files": {str(link): _link_entry(link, launcher)},
        "settings": _settings_manifest(settings_path, "claude", clone,
                                       existed, previous),
    }
    atomic_write(manifest_path,
                 json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("installed kinetic for harness claude")
    print(f"  launcher: {link} -> {launcher}")
    print(f"  settings: harness=claude clone={clone} in {settings_path}")
    print(f"  manifest: {manifest_path}")
    print()
    print("Claude Code: register the clone as a plugin (kinetic does not "
          "automate this):")
    print(f"  claude --plugin-dir {clone}")
    print()
    print("Make sure ~/.local/bin is on your PATH (it is on most macOS/Linux "
          "setups; add it to your shell profile if `kinetic` is not found), "
          "then re-run `kinetic install --harness claude` after `git pull` "
          "to pick up updates.")
    return 0


# ---------------------------------------------------------------------------
# Devin CLI
#
# `kinetic install --harness devin` registers the clone as a local Devin
# plugin (`devin plugins install --local <clone>`; Devin reads
# .claude-plugin/plugin.json and namespaces skills /kinetic:<name>). The
# clone's hooks/hooks.json is Claude-format with `--harness claude` baked in
# and Claude tool-name matchers, so the installer writes a Devin-format hook
# config (Devin tool names, `--harness devin`) into the "hooks" key of
# ~/.config/devin/config.json, preserving every foreign entry. Entries are
# marked by the `--harness devin` command flag so re-installs replace them
# and --uninstall removes exactly them.


def _devin_config_path(home: Path) -> Path:
    return home / ".config" / "devin" / "config.json"


def _plugin_name(clone: Path) -> str:
    """The plugin name Devin namespaces skills under (/<name>:<skill>), read
    from the clone's plugin manifest; 'kinetic' when none names it."""
    for rel in (".devin-plugin/plugin.json", ".claude-plugin/plugin.json",
                "plugin.json"):
        try:
            data = json.loads((clone / rel).read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("name"), str) \
                and data["name"]:
            return data["name"]
    return "kinetic"


def _write_ops_matcher(shell: str) -> str:
    """PreToolUse matcher for the shell tool plus tracker write MCP tools."""
    return (f"^{shell}$"
            "|mcp__.*atlassian.*(create|edit|Edit|update|transition|"
            "[Cc]omment|executeWrite|executeDestructive).*"
            "|mcp__.*github.*(create_pull_request|merge_pull_request|"
            "update_pull_request|push_files|create_or_update_file|"
            "create_branch|delete_file).*")


def _hook_spec(edit_matcher: str, shell: str) -> list:
    """(event, matcher, script) triples mirroring hooks/hooks.json for one
    harness: edit_matcher covers the file-edit tools (the patch tool
    included), shell the shell tool."""
    return [
        ("PostToolUse", edit_matcher, "record_edit.py"),
        ("PostToolUse", f"^{shell}$", "claim_run.py"),
        ("Stop", "", "completion_gate.py"),
        ("PreToolUse", edit_matcher, "isolation.py"),
        ("PreToolUse", _write_ops_matcher(shell), "confirm_write_ops.py"),
        ("PreToolUse", "mcp__.*deploy.*|mcp__.*tekton.*trigger.*",
         "confirm_deploy.py"),
        ("SessionStart", "", "orient.py"),
    ]


def _edit_names(tools: dict, *extra: str) -> str:
    """'|'-joined edit-tool matcher alternation: the profile's edit list,
    its patch tool and any harness-specific aliases, deduped."""
    names = list(tools.get("edit") or [])
    if tools.get("patch") and tools["patch"] not in names:
        names.append(tools["patch"])
    names += [e for e in extra if e not in names]
    return "|".join(names)


def _devin_hook_spec() -> list:
    """(event, matcher, script) triples mirroring hooks/hooks.json with
    Devin tool names taken from the harness profile. Devin's apply_patch
    is a file-edit tool too, so it joins the edit matcher (the devin
    normalizer extracts its patch-header paths)."""
    tools = harness.profile("devin")["tools"]
    edit = _edit_names(tools) or "a^"  # matches nothing when empty
    return _hook_spec(f"^({edit})$", tools["shell"])


def _hook_groups(clone: Path, harness_id: str, spec: list) -> dict:
    """{event: [matcher group, ...]} in the harness's hook config format."""
    groups = {}
    for event, matcher, script in spec:
        groups.setdefault(event, []).append({
            "matcher": matcher,
            "hooks": [{"type": "command",
                       "command": f'python3 "{clone}/hooks/{script}.py"'
                                  f" --harness {harness_id}",
                       "timeout": 10}]})
    return groups


def _devin_hook_groups(clone: Path) -> dict:
    """{event: [matcher group, ...]} in Devin's hook config format."""
    return _hook_groups(clone, "devin", _devin_hook_spec())


def _hook_commands(groups: dict) -> list:
    """Every command string in a {event: [matcher group, ...]} hooks object."""
    return [h["command"]
            for event_groups in groups.values()
            for g in event_groups for h in g["hooks"]]


def devin_hook_commands(clone: Path) -> list:
    """The hook command strings the Devin installer writes into the Devin
    config; doctor compares these against what is actually registered."""
    return _hook_commands(_devin_hook_groups(clone))


def _merge_devin_config(cfg: dict, clone: Path) -> dict:
    """Return cfg with kinetic's Devin hooks merged into cfg["hooks"],
    replacing any previously generated entries. Raises ValueError when the
    existing "hooks" value is not an object."""
    hooks = cfg.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" in the Devin config must be a JSON object')
    cfg["hooks"] = _merge_hook_groups(hooks, _devin_hook_groups(clone),
                                      "--harness devin")
    return cfg


def _read_json_object(path: Path):
    """(data, existed): {} / False for a missing file; ValueError on
    unreadable, non-JSON or non-object content."""
    if not os.path.lexists(path):
        return {}, False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot parse {path}: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data, True


def _devin_plugins_install(exe: str, clone: Path, name: str) -> int:
    """`devin plugins install --local <clone>` with inherited stdio so the
    trust prompt reaches the user. An already-installed plugin is fine: a
    --local install is linked, so its content already tracks the clone."""
    rc = subprocess.run([exe, "plugins", "install", "--local",
                         str(clone)]).returncode
    if rc == 0:
        return 0
    lst = subprocess.run([exe, "plugins", "list"],
                         capture_output=True, text=True)
    if lst.returncode == 0 and name in lst.stdout.split():
        print(f"kinetic install: devin plugin '{name}' already installed "
              f"(linked to {clone}); continuing")
        return 0
    print("kinetic install: `devin plugins install --local` failed; run "
          f"`devin plugins install --local {clone}` manually to see why",
          file=sys.stderr)
    return 1


def _install_devin(clone: Path, home: Path) -> int:
    launcher = clone / "bin" / "kinetic"
    link = _bin_dir(home) / "kinetic"
    manifest_path = _manifest_path(home, "devin")
    prev = _read_manifest(manifest_path) or {}
    prev_files = prev.get("files") or {}
    name = _plugin_name(clone)
    devin_cfg_path = _devin_config_path(home)

    exe = shutil.which("devin")
    if exe is None:
        print("kinetic install: 'devin' CLI not found on PATH; install Devin "
              "CLI and run `devin auth login` first", file=sys.stderr)
        return 1

    # Preflight the merge targets so a bad config fails before anything is
    # written or devin is invoked.
    try:
        devin_cfg, devin_existed = _read_json_object(devin_cfg_path)
        merged_cfg = _merge_devin_config(dict(devin_cfg), clone)
    except ValueError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return 1
    # Like settings, keep the FIRST install's existed flag so --uninstall
    # still knows whether it created the file.
    prev_dconf = prev.get("devin_config") or {}
    if prev_dconf.get("path") == str(devin_cfg_path):
        devin_existed = bool(prev_dconf.get("existed", devin_existed))
    try:
        _load(_settings_path(home))
    except ConfigError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return 1

    # The plugin registration is the external step: run it before writing
    # any local state so a failure (not signed in, trust declined) leaves
    # nothing behind. Local --local plugins are linked, so a re-run after a
    # later failure is tolerated by the already-installed fallback.
    if _devin_plugins_install(exe, clone, name) != 0:
        return 1

    if _ensure_link(link, launcher, prev_files) != 0:
        return 1
    res = _write_install_settings(home, clone, "devin", prev)
    if res is None:
        return 1
    settings_path, existed, previous = res

    devin_cfg_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(devin_cfg_path,
                 json.dumps(merged_cfg, indent=2, sort_keys=True) + "\n")

    manifest = {
        "version": MANIFEST_VERSION,
        "harness": "devin",
        "clone": str(clone),
        "files": {str(link): _link_entry(link, launcher)},
        "settings": _settings_manifest(settings_path, "devin", clone,
                                       existed, previous),
        "devin_config": {"path": str(devin_cfg_path),
                         "existed": devin_existed},
        "plugin": {"name": name, "scope": "local"},
    }
    atomic_write(manifest_path,
                 json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("installed kinetic for harness devin")
    print(f"  launcher: {link} -> {launcher}")
    print(f"  plugin: devin plugins install --local {clone} "
          f"(skills as /{name}:<skill>)")
    print(f"  hooks: {devin_cfg_path} (Devin format, --harness devin)")
    print(f"  settings: harness=devin clone={clone} in {settings_path}")
    print(f"  manifest: {manifest_path}")
    print()
    print("Verify inside Devin: /hooks lists kinetic's hooks and "
          "/kinetic:<skill> resolves. See docs/smoke/devin.md for the "
          "support checklist.")
    print()
    print("Make sure ~/.local/bin is on your PATH (it is on most macOS/Linux "
          "setups; add it to your shell profile if `kinetic` is not found), "
          "then re-run `kinetic install --harness devin` after `git pull` "
          "to pick up updates (a --local plugin tracks the clone).")
    return 0


# ---------------------------------------------------------------------------
# Codex CLI
#
# `kinetic install --harness codex` is file generation only; it never shells
# out to codex, so the CLI is not required on PATH (like OpenCode it is only
# reported when missing — hook trust is a manual /hooks step inside Codex
# anyway). Codex discovers skills under ~/.agents/skills, sub-agent
# definitions under ~/.codex/agents/*.toml
# and hooks in ~/.codex/hooks.json — the same
# {event: [{matcher, hooks: [{type, command, ...}]}]} shape Claude uses, so
# foreign entries merge exactly like Devin's. Each skill becomes a
# kntc-<name> stub whose body points at the clone's skills/<name>/SKILL.md;
# skills whose source frontmatter sets disable-model-invocation: true (the
# user-only set plus doctor) also get an agents/openai.yaml sidecar with
# policy.allow_implicit_invocation: false. Each agents/*.md becomes a TOML
# file with the tier resolved through harness.resolve_tier. Hook entries are
# marked by `--harness codex` so re-installs replace them and --uninstall
# removes exactly them. Codex additionally gates hooks behind interactive
# trust (/hooks writes trusted_hash state into ~/.codex/config.toml
# [hooks.state]); doctor verifies that state, this installer only prints the
# instruction.


def _codex_dir(home: Path) -> Path:
    # CODEX_HOME is not honoured: every kinetic path is derived from Path.home()
    # so install, doctor and the hooks agree on one location.
    return home / ".codex"


def _codex_hooks_path(home: Path) -> Path:
    return _codex_dir(home) / "hooks.json"


def _codex_agents_dir(home: Path) -> Path:
    return _codex_dir(home) / "agents"


def _agents_skills_dir(home: Path) -> Path:
    return home / ".agents" / "skills"


def _fm_scalar(raw: str):
    """One frontmatter value: inline list, bool, quoted or plain scalar."""
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_fm_scalar(v) for v in inner.split(",")] if inner else []
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


def _split_frontmatter(path: Path):
    """(fields, body) for a markdown file with a --- fenced frontmatter block.
    Only single-line `key: value` pairs are read — all kinetic sources use
    that shape."""
    lines = path.read_text().splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: missing frontmatter")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError(f"{path}: unterminated frontmatter")
    fields = {}
    for line in lines[1:end]:
        key, sep, raw = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key:
            fields[key] = _fm_scalar(raw)
    return fields, "".join(lines[end + 1:]).lstrip("\n")


def _toml_basic(text: str) -> str:
    """A TOML basic-string literal; JSON string syntax is a valid subset."""
    return json.dumps(str(text), ensure_ascii=False)


def _toml_instructions(body: str) -> str:
    """developer_instructions value: a literal ''' block when safe, else a
    basic string (a body containing ''' or ending in ' cannot use one)."""
    text = body.strip("\n")
    if not text:
        return '""'
    if "'''" in text or text.endswith("'") or "\r" in text:
        return _toml_basic(text)
    return "'''\n" + text + "\n'''"


def _skill_entry(skill_md: Path):
    """(name, fields) for a skills/<name>/SKILL.md after the checks every
    harness's skill generator shares: the frontmatter name must equal the
    directory name and a description must be present."""
    fields, _body = _split_frontmatter(skill_md)
    # the directory name is what harnesses discover; frontmatter name must
    # agree or the stub would point at the wrong source path
    name = skill_md.parent.name
    fm_name = fields.get("name")
    if fm_name is not None and fm_name != name:
        raise ValueError(
            f"{skill_md}: frontmatter name {fm_name!r} != directory "
            f"{name!r}")
    desc = fields.get("description")
    if not isinstance(desc, str) or not desc:
        raise ValueError(
            f"{skill_md}: frontmatter needs a description")
    return name, fields


def _codex_skill_files(clone: Path, skills_root: Path) -> dict:
    """{path: text} for every kntc-<name> stub skill, plus agents/openai.yaml
    sidecars for user-only skills (disable-model-invocation: true)."""
    skills_src = clone / "skills"
    if not skills_src.is_dir():
        raise ValueError(f"{skills_src} is missing; cannot generate skills")
    out = {}
    for skill_md in sorted(skills_src.glob("*/SKILL.md")):
        name, fields = _skill_entry(skill_md)
        desc = fields["description"]
        stub_dir = skills_root / f"kntc-{name}"
        out[stub_dir / "SKILL.md"] = (
            "---\n"
            f"name: kntc-{name}\n"
            f"description: {json.dumps('kinetic: ' + desc, ensure_ascii=False)}\n"
            "---\n\n"
            f"Read and follow `{clone}/skills/{name}/SKILL.md`.\n")
        if fields.get("disable-model-invocation") is True:
            out[stub_dir / "agents" / "openai.yaml"] = (
                "policy:\n  allow_implicit_invocation: false\n")
    if not out:
        raise ValueError(f"{skills_src}: no skills found")
    return out


def _agent_skills(fields: dict) -> list:
    """The agent's skills: frontmatter list ([] when absent)."""
    skills = fields.get("skills") or []
    if isinstance(skills, str):
        skills = [skills]
    return [str(s) for s in skills]


def _agent_entry(md: Path, harness_id: str, settings_path: Path):
    """(name, fields, body, resolved) for agents/<name>.md after the checks
    every harness's agent generator shares; the tier resolves through
    harness.resolve_tier for harness_id so settings.json tiers apply."""
    fields, body = _split_frontmatter(md)
    name = md.stem
    fm_name = fields.get("name")
    if fm_name is not None and fm_name != name:
        raise ValueError(f"{md}: frontmatter name {fm_name!r} != file {name!r}")
    desc = fields.get("description")
    tier = fields.get("tier")
    if not isinstance(desc, str) or not desc \
            or not isinstance(tier, str) or not tier:
        raise ValueError(f"{md}: frontmatter needs description and tier")
    try:
        resolved = harness.resolve_tier(harness_id, tier,
                                        settings=settings_path)
    except harness.HarnessError as e:
        raise ValueError(f"{md}: {e}")
    return name, fields, body, resolved


def _codex_agent_files(clone: Path, agents_root: Path,
                       settings_path: Path) -> dict:
    """{path: text} of ~/.codex/agents/<name>.toml generated from agents/*.md.
    The Claude-only frontmatter keys model/tools have no Codex agent
    equivalent (tools are not restricted per-agent on Codex)."""
    agents_src = clone / "agents"
    if not agents_src.is_dir():
        raise ValueError(f"{agents_src} is missing; cannot generate agents")
    out = {}
    for md in sorted(agents_src.glob("*.md")):
        name, fields, body, resolved = _agent_entry(md, "codex",
                                                    settings_path)
        desc = fields["description"]
        lines = [
            f"name = {_toml_basic(name)}",
            f"description = {_toml_basic(desc)}",
            f"developer_instructions = {_toml_instructions(body)}",
        ]
        if resolved.get("model"):
            lines.append(f"model = {_toml_basic(resolved['model'])}")
        if resolved.get("effort"):
            lines.append(
                f"model_reasoning_effort = {_toml_basic(resolved['effort'])}")
        for skill in _agent_skills(fields):
            lines += ["", "[[skills.config]]",
                      f"name = {_toml_basic('kntc-' + skill)}",
                      "enabled = true"]
        out[agents_root / f"{name}.toml"] = "\n".join(lines) + "\n"
    if not out:
        raise ValueError(f"{agents_src}: no agents found")
    return out


def _codex_hook_spec() -> list:
    """(event, matcher, script) triples mirroring hooks/hooks.json with Codex
    tool names. apply_patch is Codex's only file-edit tool; its matcher also
    answers to the Write/Edit aliases Codex registers for it."""
    tools = harness.profile("codex")["tools"]
    edit = _edit_names(tools, "Write", "Edit")
    return _hook_spec(edit, tools["shell"])


def codex_hook_groups(clone: Path) -> dict:
    """{event: [matcher group, ...]} in Codex's hooks.json format."""
    return _hook_groups(clone, "codex", _codex_hook_spec())


def codex_hook_commands(clone: Path) -> list:
    """The hook command strings the Codex installer writes into hooks.json;
    doctor compares these against what is actually registered."""
    return _hook_commands(codex_hook_groups(clone))


def _strip_marked_hooks(hooks: dict, marker: str) -> dict:
    """hooks minus every hook entry whose command contains marker; groups
    left empty are dropped. Malformed event values and groups are preserved."""
    out = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept_groups = []
        for g in groups:
            ghooks = g.get("hooks") if isinstance(g, dict) else None
            if not isinstance(ghooks, list):
                kept_groups.append(g)
                continue
            kept = [h for h in ghooks
                    if not (isinstance(h, dict)
                            and marker in str(h.get("command") or ""))]
            if kept:
                kept_groups.append({**g, "hooks": kept})
        if kept_groups:
            out[event] = kept_groups
        # an event left with no groups is dropped (equivalent to [])
    return out


def _merge_hook_groups(hooks: dict, new_groups: dict,
                       marker: str) -> dict:
    """hooks with new_groups merged per event after stripping entries that
    carry marker. A non-list foreign event value is preserved and ours is
    skipped for that event."""
    merged = _strip_marked_hooks(hooks, marker)
    for event, groups in new_groups.items():
        existing = merged.get(event)
        if existing is None:
            merged[event] = list(groups)
        elif isinstance(existing, list):
            existing.extend(groups)
    return merged


def _merge_codex_hooks_file(cfg: dict, clone: Path) -> dict:
    """Return cfg (a Codex hooks.json object) with kinetic's hook groups
    merged into cfg["hooks"], replacing previously generated entries.
    Raises ValueError when the existing "hooks" value is not an object."""
    hooks = cfg.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" in the Codex hooks.json must be a JSON object')
    cfg["hooks"] = _merge_hook_groups(hooks, codex_hook_groups(clone),
                                      "--harness codex")
    return cfg


def _codex_generated_files(clone: Path, home: Path,
                           settings_path: Path) -> dict:
    """All files _install_codex writes, {path: text}, for preflight and
    manifest recording."""
    out = _codex_skill_files(clone, _agents_skills_dir(home))
    out.update(_codex_agent_files(clone, _codex_agents_dir(home),
                                  settings_path))
    return out


def _install_codex(clone: Path, home: Path) -> int:
    launcher = clone / "bin" / "kinetic"
    link = _bin_dir(home) / "kinetic"
    manifest_path = _manifest_path(home, "codex")
    prev = _read_manifest(manifest_path) or {}
    prev_files = prev.get("files") or {}
    hooks_path = _codex_hooks_path(home)
    settings_path = _settings_path(home)

    # Preflight everything that can fail before any file is written. The
    # settings check comes first: tier resolution reads it.
    try:
        _load(settings_path)
    except ConfigError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return 1
    try:
        generated = _codex_generated_files(clone, home, settings_path)
        hooks_cfg, hooks_existed = _read_json_object(hooks_path)
        merged_hooks = _merge_codex_hooks_file(dict(hooks_cfg), clone)
    except ValueError as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return 1
    prev_hcfg = prev.get("codex_hooks") or {}
    if prev_hcfg.get("path") == str(hooks_path):
        hooks_existed = bool(prev_hcfg.get("existed", hooks_existed))

    if _ensure_link(link, launcher, prev_files) != 0:
        return 1
    res = _write_install_settings(home, clone, "codex", prev)
    if res is None:
        return 1
    sp, existed, previous = res

    _write_generated_files(generated)
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(hooks_path,
                 json.dumps(merged_hooks, indent=2, sort_keys=True) + "\n")

    manifest = {
        "version": MANIFEST_VERSION,
        "harness": "codex",
        "clone": str(clone),
        "files": _generated_files(link, launcher, generated),
        "settings": _settings_manifest(sp, "codex", clone, existed, previous),
        "codex_hooks": {"path": str(hooks_path), "existed": hooks_existed},
    }
    atomic_write(manifest_path,
                 json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("installed kinetic for harness codex")
    print(f"  launcher: {link} -> {launcher}")
    print(f"  skills: {len(generated)} generated files under "
          f"{_agents_skills_dir(home)} (invoke as $kntc-<name>)")
    print(f"  agents: {_codex_agents_dir(home)}/*.toml")
    print(f"  hooks: {hooks_path} (merged, --harness codex)")
    print(f"  settings: harness=codex clone={clone} in {sp}")
    print(f"  manifest: {manifest_path}")
    print()
    if shutil.which("codex") is None:
        print("note: 'codex' CLI not found on PATH; the generated files "
              "still load next time Codex starts, but its hooks stay "
              "inactive until trusted with /hooks.")
    print()
    print("Codex CLI: open Codex and run /hooks to review and trust "
          "kinetic's hooks — they stay inactive until trusted. "
          "kinetic doctor reports trust state.")
    print()
    print("Make sure ~/.local/bin is on your PATH (it is on most macOS/Linux "
          "setups; add it to your shell profile if `kinetic` is not found), "
          "then re-run `kinetic install --harness codex` after `git pull` "
          "to pick up updates.")
    return 0


# ---------------------------------------------------------------------------
# OpenCode
#
# `kinetic install --harness opencode` is file generation only, like Codex:
# OpenCode discovers plugins as *.ts files under ~/.config/opencode/plugins,
# skills under ~/.config/opencode/skills and agents under
# ~/.config/opencode/agents — no config-file merge and no trust step, so the
# installer writes files and records them in the manifest; it never edits
# opencode.json and never shells out to opencode (the CLI is only reported
# missing, since file-drop plugins also serve desktop/alternate installs).
# Each skill becomes a flat kntc-<name>.md stub whose body points at the
# clone's skills/<name>/SKILL.md; user-only skills carry
# disable-model-invocation: true, which OpenCode honours natively. Each
# agents/*.md becomes a markdown agent whose tier resolves through
# harness.resolve_tier and whose Claude tools: allow-list maps onto
# OpenCode permission denies for the capability groups it omits. The plugin
# (templates/opencode-plugin.ts with the clone path baked in) forwards
# tool.execute.before/after, permission.evaluate, experimental.idle and
# session context events to the Python hooks.


def _opencode_dir(home: Path) -> Path:
    return home / ".config" / "opencode"


def _opencode_skills_dir(home: Path) -> Path:
    return _opencode_dir(home) / "skills"


def _opencode_agents_dir(home: Path) -> Path:
    return _opencode_dir(home) / "agents"


def _opencode_plugin_path(home: Path) -> Path:
    return _opencode_dir(home) / "plugins" / "kinetic.ts"


def _opencode_skill_files(clone: Path, skills_root: Path) -> dict:
    """{path: text} for every flat kntc-<name>.md stub skill. OpenCode reads
    disable-model-invocation frontmatter natively, so user-only skills need
    no sidecar (unlike Codex's agents/openai.yaml)."""
    skills_src = clone / "skills"
    if not skills_src.is_dir():
        raise ValueError(f"{skills_src} is missing; cannot generate skills")
    out = {}
    for skill_md in sorted(skills_src.glob("*/SKILL.md")):
        name, fields = _skill_entry(skill_md)
        desc = fields["description"]
        fm = ["---",
              f"name: kntc-{name}",
              f"description: {json.dumps('kinetic: ' + desc, ensure_ascii=False)}"]
        if fields.get("disable-model-invocation") is True:
            fm.append("disable-model-invocation: true")
        fm.append("---")
        out[skills_root / f"kntc-{name}.md"] = (
            "\n".join(fm) + "\n\n"
            f"Read and follow `{clone}/skills/{name}/SKILL.md`.\n")
    if not out:
        raise ValueError(f"{skills_src}: no skills found")
    return out


# Claude tool names -> the OpenCode permission action that covers them, used
# to translate an agent's tools: allow-list into deny rules for the groups it
# omits (OpenCode permissions are last-match-wins deny/ask/allow rules; a
# subagent with no edit tools gets {action: edit, effect: deny}).
_OPENCODE_AGENT_ACTIONS = {
    "edit": {"Write", "Edit", "MultiEdit", "NotebookEdit"},
    "shell": {"Bash", "exec", "shell"},
    "read": {"Read"},
    "grep": {"Grep"},
    "glob": {"Glob", "GlobTool"},
    "webfetch": {"WebFetch", "webfetch"},
    "websearch": {"WebSearch", "websearch"},
    "subagent": {"Task", "Agent", "run_subagent"},
}


def _opencode_agent_tools(fields: dict) -> set:
    """The agent's tools: allow-list as a set of names ([] when absent)."""
    tools = fields.get("tools") or []
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]
    return {str(t).strip() for t in tools if str(t).strip()}


def _opencode_permissions(fields: dict) -> list:
    """Deny rules for capability groups missing from the tools: allow-list.
    No tools: frontmatter means no allow-list, so no denies."""
    tools = _opencode_agent_tools(fields)
    if not tools:
        return []
    denies = []
    for action in sorted(_OPENCODE_AGENT_ACTIONS):
        if not (_OPENCODE_AGENT_ACTIONS[action] & tools):
            denies.append({"action": action, "resource": "*",
                           "effect": "deny"})
    return denies


def _opencode_agent_body(fields: dict, body: str, clone: Path) -> str:
    """Rewrite the source body's 'The `<skill>` skill is preloaded' claim.
    OpenCode agent frontmatter has no skill-preload mechanism (unlike
    Claude's skills: list or Codex's [[skills.config]]), so the generated
    agent is pointed at the clone's skill file instead."""
    for skill in _agent_skills(fields):
        claim = re.compile(r"The `" + re.escape(skill)
                           + r"` skill is preloaded([^.\n]*)\.")

        def _repl(m, skill=skill):
            tail = m.group(1).lstrip(" :")
            text = (f"On OpenCode the `{skill}` skill is not preloaded — "
                    f"read `{clone}/skills/{skill}/SKILL.md`")
            return text + (f" and {tail}." if tail else ".")
        body = claim.sub(_repl, body)
    return body


def _opencode_agent_files(clone: Path, agents_root: Path,
                          settings_path: Path) -> dict:
    """{path: text} of ~/.config/opencode/agents/<name>.md generated from
    agents/*.md. Frontmatter accepts description/mode/model/permissions; the
    markdown body becomes the system prompt. Every kinetic agent is a
    dispatched subagent, so mode is always subagent; the tier resolves
    through harness.resolve_tier so settings.json tiers.opencode applies."""
    agents_src = clone / "agents"
    if not agents_src.is_dir():
        raise ValueError(f"{agents_src} is missing; cannot generate agents")
    out = {}
    for md in sorted(agents_src.glob("*.md")):
        name, fields, body, resolved = _agent_entry(md, "opencode",
                                                    settings_path)
        desc = fields["description"]
        fm = ["---",
              f"description: {json.dumps(desc, ensure_ascii=False)}",
              "mode: subagent"]
        if resolved.get("model"):
            fm.append(f"model: {json.dumps(resolved['model'])}")
        perms = _opencode_permissions(fields)
        if perms:
            fm.append("permissions:")
            for p in perms:
                fm += [f"- action: {p['action']}",
                       f"  resource: {json.dumps(p['resource'])}",
                       f"  effect: {p['effect']}"]
        fm.append("---")
        out[agents_root / f"{name}.md"] = (
            "\n".join(fm) + "\n\n"
            + _opencode_agent_body(fields, body.strip("\n"), clone) + "\n")
    if not out:
        raise ValueError(f"{agents_src}: no agents found")
    return out


def _opencode_plugin_text(clone: Path) -> str:
    """templates/opencode-plugin.ts with the clone path baked in as a JSON
    string literal (valid JS)."""
    tpl_path = clone / "templates" / "opencode-plugin.ts"
    try:
        tpl = tpl_path.read_text()
    except OSError as e:
        raise ValueError(f"cannot read {tpl_path}: {e}")
    if "__KINETIC_CLONE__" not in tpl:
        raise ValueError(f"{tpl_path}: missing __KINETIC_CLONE__ placeholder")
    return tpl.replace("__KINETIC_CLONE__", json.dumps(str(clone)))


def _opencode_generated_files(clone: Path, home: Path,
                              settings_path: Path) -> dict:
    """All files _install_opencode writes, {path: text}, for preflight and
    manifest recording."""
    out = _opencode_skill_files(clone, _opencode_skills_dir(home))
    out.update(_opencode_agent_files(clone, _opencode_agents_dir(home),
                                     settings_path))
    out[_opencode_plugin_path(home)] = _opencode_plugin_text(clone)
    return out


def _install_opencode(clone: Path, home: Path) -> int:
    launcher = clone / "bin" / "kinetic"
    link = _bin_dir(home) / "kinetic"
    manifest_path = _manifest_path(home, "opencode")
    prev = _read_manifest(manifest_path) or {}
    prev_files = prev.get("files") or {}
    settings_path = _settings_path(home)

    # Preflight everything that can fail before any file is written. Unlike
    # codex/devin the opencode CLI is not required on PATH: plugins are
    # file-dropped into ~/.config/opencode/plugins and also serve installs
    # whose binary is not on PATH (desktop app, version managers).
    try:
        _load(settings_path)
        generated = _opencode_generated_files(clone, home, settings_path)
    except (ConfigError, ValueError, OSError) as e:
        print(f"kinetic install: {e}", file=sys.stderr)
        return 1
    n_skills = sum(1 for p in generated
                   if p.parent == _opencode_skills_dir(home))
    n_agents = sum(1 for p in generated
                   if p.parent == _opencode_agents_dir(home))

    if _ensure_link(link, launcher, prev_files) != 0:
        return 1
    res = _write_install_settings(home, clone, "opencode", prev)
    if res is None:
        return 1
    sp, existed, previous = res

    _write_generated_files(generated)

    manifest = {
        "version": MANIFEST_VERSION,
        "harness": "opencode",
        "clone": str(clone),
        "files": _generated_files(link, launcher, generated),
        "settings": _settings_manifest(sp, "opencode", clone, existed, previous),
    }
    atomic_write(manifest_path,
                 json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("installed kinetic for harness opencode")
    print(f"  launcher: {link} -> {launcher}")
    print(f"  skills: {n_skills} stubs under {_opencode_skills_dir(home)} "
          f"(kntc-<name>)")
    print(f"  agents: {n_agents} files under {_opencode_agents_dir(home)}")
    print(f"  plugin: {_opencode_plugin_path(home)}")
    print(f"  settings: harness=opencode clone={clone} in {sp}")
    print(f"  manifest: {manifest_path}")
    print()
    if shutil.which("opencode") is None:
        print("note: 'opencode' CLI not found on PATH; the plugin still "
              "loads next time OpenCode starts (file-drop plugins need no "
              "registration).")
    print()
    print("OpenCode loads ~/.config/opencode/plugins/*.ts automatically; "
          "no config edit or trust step is needed. Verify with "
          "docs/smoke/opencode.md.")
    print()
    print("Make sure ~/.local/bin is on your PATH (it is on most macOS/Linux "
          "setups; add it to your shell profile if `kinetic` is not found), "
          "then re-run `kinetic install --harness opencode` after `git pull` "
          "to pick up updates.")
    return 0


def _strip_marked_config(path: Path, existed: bool, marker: str):
    """Remove every hook entry whose command contains marker from a JSON
    config's "hooks" object (a Codex hooks.json or a Devin config.json —
    same shape), preserving everything else. Returns a warning or None."""
    if not path.is_file():
        return None
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return f"left {path}: {e}"
    if not isinstance(cfg, dict):
        return f"left {path}: not a JSON object"
    hooks = cfg.get("hooks")
    if isinstance(hooks, dict):
        stripped = _strip_marked_hooks(hooks, marker)
        if stripped:
            cfg["hooks"] = stripped
        else:
            cfg.pop("hooks", None)
    elif hooks is not None:
        return f"left {path}: 'hooks' is not an object; kinetic hooks may remain"
    if not cfg:
        if existed:
            atomic_write(path, "{}\n")
        else:
            path.unlink()
        return None
    atomic_write(path, json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    return None


def _remove_listed(path: Path, meta: dict):
    """Remove one manifest-listed path. Returns a warning or None."""
    mtype = meta.get("type")
    want_hash = meta.get("sha256")
    if mtype == "symlink":
        if os.path.islink(path):
            if os.readlink(path) == meta.get("target") and \
                    _hash_link(path) == want_hash:
                path.unlink()
                return None
            return f"left {path}: symlink target changed since install"
        if os.path.lexists(path):
            return f"left {path}: no longer a symlink"
        return None
    if path.is_symlink() or not path.is_file():
        if os.path.lexists(path):
            return f"left {path}: unexpected file type"
        return None
    if want_hash and _hash_file(path) != want_hash:
        return f"left {path}: content changed since install"
    path.unlink()
    return None


def _other_manifest_files(home: Path, harness_id: str) -> set:
    """Paths other harnesses' manifests still claim as generated files, so
    this uninstall does not remove a launcher another install needs."""
    claimed = set()
    cfgdir = _config_dir(home)
    if not cfgdir.is_dir():
        return claimed
    for mp in cfgdir.glob("install-manifest-*.json"):
        if mp.name == f"install-manifest-{harness_id}.json":
            continue
        m = _read_manifest(mp)
        if m:
            claimed.update((m.get("files") or {}).keys())
    return claimed


def _uninstall(harness_id: str, home: Path) -> int:
    manifest_path = _manifest_path(home, harness_id)
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        print(f"kinetic install: nothing installed for harness {harness_id}")
        return 0

    warnings = []
    removed = []
    kept = []
    claimed = _other_manifest_files(home, harness_id)
    for name, meta in sorted((manifest.get("files") or {}).items()):
        if name in claimed:
            kept.append(f"{name} (also installed for another harness)")
            continue
        path = Path(name)
        warn = _remove_listed(path, meta)
        if warn:
            warnings.append(warn)
        else:
            removed.append(name)

    sent = manifest.get("settings") or {}
    sp = Path(sent["path"]) if sent.get("path") else None
    if sp is not None and sp.is_file():
        try:
            cfg = _load(sp)
        except ConfigError as e:
            cfg = None
            warnings.append(f"left {sp}: {e}")
        if cfg is not None:
            changed = False
            for key, written in (sent.get("writes") or {}).items():
                if cfg.get(key) == written:
                    prev = (sent.get("previous") or {}).get(key)
                    if prev is None:
                        cfg.pop(key, None)
                    else:
                        cfg[key] = prev
                    changed = True
                elif key in cfg:
                    warnings.append(
                        f"settings key '{key}' in {sp} changed since "
                        f"install; left as is")
            if changed:
                if not cfg and not sent.get("existed", True):
                    sp.unlink()
                    removed.append(str(sp))
                else:
                    atomic_write(sp, json.dumps(cfg, indent=2,
                                                sort_keys=True) + "\n")
                    removed.append(str(sp))

    dconf = manifest.get("devin_config")
    if isinstance(dconf, dict) and dconf.get("path"):
        dpath = Path(dconf["path"])
        warn = _strip_marked_config(dpath, bool(dconf.get("existed")),
                                    "--harness devin")
        if warn:
            warnings.append(warn)
        elif dpath.exists():
            kept.append(str(dpath) + " (foreign entries kept)")

    cconf = manifest.get("codex_hooks")
    if isinstance(cconf, dict) and cconf.get("path"):
        cpath = Path(cconf["path"])
        warn = _strip_marked_config(cpath, bool(cconf.get("existed")),
                                    "--harness codex")
        if warn:
            warnings.append(warn)
        elif cpath.exists():
            kept.append(str(cpath) + " (foreign entries kept)")

    # prune directories that only held files this uninstall removed
    # (kntc-<name>/ and kntc-<name>/agents/ under ~/.agents/skills,
    # ~/.codex/agents, ~/.config/opencode/skills and .../agents when empty)
    stops = (_agents_skills_dir(home), _codex_agents_dir(home),
             _opencode_skills_dir(home), _opencode_agents_dir(home))
    dirs = set()
    for name in removed:
        p = Path(name)
        for stop in stops:
            try:
                p.relative_to(stop)
            except ValueError:
                continue
            cur = p
            while cur != stop:
                dirs.add(cur)
                cur = cur.parent
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    for stop in stops:
        try:
            stop.rmdir()
        except OSError:
            pass

    plugin = manifest.get("plugin")
    pname = plugin.get("name") if isinstance(plugin, dict) else None
    if isinstance(pname, str) and pname:
        exe = shutil.which("devin")
        if exe is None:
            warnings.append(
                f"devin CLI not on PATH; remove the plugin manually: "
                f"devin plugins remove {pname} --local")
        else:
            rc = subprocess.run([exe, "plugins", "remove", pname,
                                 "--local"]).returncode
            if rc != 0:
                warnings.append(
                    f"`devin plugins remove {pname} --local` failed; "
                    "remove the plugin manually")

    manifest_path.unlink(missing_ok=True)
    removed.append(str(manifest_path))
    for d in (_config_dir(home), _bin_dir(home)):
        try:
            d.rmdir()
        except OSError:
            pass

    print(f"uninstalled kinetic for harness {harness_id}")
    for name in removed:
        print(f"  removed: {name}")
    for name in kept:
        print(f"  kept: {name}")
    for w in warnings:
        print(f"  warning: {w}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kinetic install")
    ap.add_argument("--harness", required=True, choices=harness.HARNESS_IDS,
                    help="harness to install for")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove everything the manifest lists")
    a = ap.parse_args(argv)

    home = Path.home()
    if a.uninstall:
        return _uninstall(a.harness, home)

    clone = _clone_root()
    err = _check_clone(clone)
    if err:
        print(f"kinetic install: {err}", file=sys.stderr)
        return 1
    installers = {"claude": _install_claude, "devin": _install_devin,
                  "codex": _install_codex, "opencode": _install_opencode}
    return installers[a.harness](clone, home)


if __name__ == "__main__":
    sys.exit(main())
