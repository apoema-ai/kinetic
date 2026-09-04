# Byond — Plan

## Context

The user wanted a Docker-based development environment that feels like a dedicated machine rather than a throwaway container: latest Ubuntu LTS, git, a way to point at any local file/folder, Claude Code, npm/npx, and Homebrew, all managed through Docker Compose. The design was worked out through a grilling session that resolved every open branch (base image, volumes, auth, install strategy, package-manager split, persistence model, user model) before any code was written.

## Decisions

- **Base image**: `ubuntu:26.04`, pinned explicitly (current LTS, "Resolute Raccoon").
- **Workspace Mount**: one `.env`-configurable read-write bind mount (`HOST_WORKSPACE_PATH` → `/workspace`), so the user can point Byond at any local project by editing `.env`.
- **Clean Install**: Claude Code is installed/updated at container startup (not baked into the image), and authenticates via `claude login` run interactively inside the container — no host `~/.claude` credentials are mounted in. See `docs/adr/0001`.
- **Package manager split**: apt + the NodeSource repo install git, build-essential, and Node.js at image-build time (root); Homebrew is installed for ad hoc extras under the non-root Byond User. See `docs/adr/0003`.
- **Node.js**: version 24 ("Krypton"), the current Active LTS as of Sept 2026, pinned explicitly via the NodeSource setup script.
- **Byond User**: fixed non-root user, UID/GID 1000, with passwordless sudo — required because Homebrew refuses to run as root. Not matched to the host UID; Docker Desktop on macOS handles that translation transparently.
- **VM-like persistence**: the container is long-running (`restart: unless-stopped`, `tty`/`stdin_open` for `docker compose exec` shells) rather than a one-shot command runner. The Byond User's entire `$HOME` (Home Volume) and the Homebrew install directory (Brew Volume) live on separate named Docker volumes, surviving `docker compose down && up` and image rebuilds. See `docs/adr/0002`.

Full vocabulary is in `CONTEXT.md`; the reasoning behind the three decisions above that were hard to reverse, non-obvious, or genuine trade-offs is recorded in `docs/adr/`.

## Files

- `Dockerfile` — builds the image: Ubuntu base, apt/NodeSource baseline tooling, the Byond User, a user-owned npm global prefix, and Homebrew.
- `entrypoint.sh` — runs on every container start as the Byond User: installs/updates Claude Code via npm, then idles (`sleep infinity`) so the container stays up for `docker compose exec` shells.
- `docker-compose.yml` — single `byond` service: builds the Dockerfile, mounts the Workspace Mount and the two named volumes (`byond_home`, `byond_brew`), `restart: unless-stopped`.
- `.env.example` — template for `HOST_WORKSPACE_PATH`; copy to `.env` (gitignored) and fill in a real path.
- `README.md` — day-to-day usage (build/up, exec, `claude login`, switching projects, resetting).
- `CONTEXT.md`, `docs/adr/0001-*.md`, `docs/adr/0002-*.md`, `docs/adr/0003-*.md` — domain vocabulary and the decisions behind the design.

## Verification

This machine has Podman, not Docker Desktop, and no `docker compose`/`podman-compose` provider was installed, so the image was built and run directly with `podman build` / `podman run` (bypassing the compose layer) to validate the Dockerfile and runtime behavior end to end:

1. **Build** — `podman build -t byond:test .` initially failed: `ubuntu:26.04` ships a built-in `ubuntu` user/group already at UID/GID 1000 (carried over from 24.04), so `groupadd --gid 1000 byond` collided with it. Fixed by removing the pre-existing `ubuntu` user/group before creating the Byond User (see `Dockerfile`). Rebuilt clean after the fix.
2. **Tool versions** — ran the image with `--entrypoint bash`: confirmed `git --version` (2.53.0), `node --version` (v24.20.0), `npm`/`npx` (11.19.0), and `brew --version` (Homebrew 6.0.21, resolved via `.bashrc`'s `brew shellenv` in a non-login interactive shell — the same shell type `docker/podman compose exec -it` opens).
3. **Runtime + entrypoint** — ran the container detached with the Workspace Mount and both named volumes attached (as `docker-compose.yml` defines them). The entrypoint installed Claude Code via npm; `claude --version` (2.1.259) and `which claude` resolved correctly inside an exec'd shell despite an `npm warn install-scripts` notice (npm's allow-scripts policy skipped a postinstall script, but the CLI still works).
4. **Workspace Mount + user identity** — `ls /workspace` inside the container showed the host folder's contents; `id` confirmed `uid=1000(byond) gid=1000(byond)`.
5. Test container, both named volumes, and the scratch workspace directory were removed after verification.

**Not yet verified** (no compose provider on this machine — see README's Prerequisites section): the `docker-compose.yml` file itself hasn't been run through `docker compose` or `podman-compose`, `claude login`'s interactive OAuth flow, and Home/Brew Volume persistence across a real `docker compose down && up` cycle. Once `podman-compose` (or Docker Desktop) is installed, re-run steps 2–7 below through `docker compose` to close that gap:

1. `cp .env.example .env` and set `HOST_WORKSPACE_PATH` to a real local folder.
2. `docker compose up -d --build`
3. `docker compose exec -it byond bash`
4. `claude login` — confirm the login flow completes inside the container.
5. `docker compose down && docker compose up -d` — reopen a shell and confirm `claude` is still logged in and any files created under `$HOME` persisted.
6. `docker compose down -v` — confirm this is the deliberate reset path (wipes both named volumes) when a clean slate is wanted.
