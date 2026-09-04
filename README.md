# Byond

A persistent, VM-like Docker Compose environment for running Claude Code, git, npm/npx, and Homebrew against any local project.

See `CONTEXT.md` for the project's vocabulary and `docs/adr/` for the reasoning behind its key decisions.

## Prerequisites

This machine has Podman (not Docker Desktop) installed, with `docker` aliased to it in the shell — but no `docker compose`/`podman-compose` provider yet. Before `docker compose` commands below will work, install one:

```
brew install podman-compose
```

(Docker Desktop, if you install it instead, ships `docker compose` built in — no separate step needed.)

The image itself was verified with plain `podman build` / `podman run` (see PLAN.md) and works correctly; only the `compose` orchestration layer needs this one-time setup.

## First-time setup

1. Copy `.env.example` to `.env` and set `HOST_WORKSPACE_PATH` to the local folder you want available inside the container.
2. Build and start:
   ```
   docker compose up -d --build
   ```
3. Open a shell:
   ```
   docker compose exec -it byond bash
   ```
4. Log in to Claude Code (one-time — the session persists on the Home Volume):
   ```
   claude login
   ```

## Day to day

- Your project files: `/workspace` inside the container, backed by `HOST_WORKSPACE_PATH` on your Mac.
- Run `claude`, `git`, `npm`/`npx`, and `brew` from the shell as usual.
- The container stays running (`restart: unless-stopped`) and keeps its state (home directory, Homebrew installs, Claude Code login) across `docker compose down && up` and image rebuilds.
- To point at a different local project, change `HOST_WORKSPACE_PATH` in `.env` and re-run `docker compose up -d`.

## Resetting

Wipe everything (login, dotfiles, brew installs) and start clean:

```
docker compose down -v
```
