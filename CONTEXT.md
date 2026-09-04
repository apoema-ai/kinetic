# Byond

Byond is a Dockerized development environment that behaves like a persistent virtual machine rather than a disposable container — one long-running box where Claude Code, git, npm, and Homebrew all live, brought up and torn down via a single Docker Compose service.

## Language

**Workspace Mount**:
The read-write bind mount, pointed at whatever local folder the user sets via `HOST_WORKSPACE_PATH`, that exposes their current project inside the container at `/workspace`. Swappable per session — it's the "what am I working on right now" mount.
_Avoid_: volume, project folder, source mount

**Home Volume**:
The named Docker volume backing the Byond User's `$HOME`, holding the Claude Code login/config, dotfiles, bash history, and npm global installs. Survives `docker compose down`/`up` and image rebuilds — it's what makes Byond feel like a machine you keep coming back to, not a container you throw away.
_Avoid_: state volume, user data, home directory

**Brew Volume**:
The named Docker volume backing `/home/linuxbrew/.linuxbrew`, kept separate from the Home Volume so Homebrew-installed formulae persist independently and can be wiped or rebuilt on their own without touching login state or dotfiles.
_Avoid_: cellar, brew cache

**Clean Install**:
The design principle that Claude Code authenticates by running `claude login` interactively inside Byond itself, rather than inheriting the host machine's existing session via a mounted credentials directory. Byond has its own identity, not a copy of the host's.
_Avoid_: fresh install, isolated login

**Byond User**:
The fixed, non-root user (UID 1000) that owns the Home Volume and the Brew Volume, and under which Homebrew, npm global installs, and Claude Code all run. Exists because Homebrew refuses to run as root.
_Avoid_: brew user, app user, container user
